# maoyan_updater_fixed.py - 修复版

# !/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from typing import Optional, Dict, List

# ==================== 配置区 ====================
MYSQL_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'root',
    'password': '20060321',  # ⚠️ 请修改
    'database': 'movie_db',
}

TMDB_API_KEY = '3a7253d0014eca94a6d059916e2fc186'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'

CRAWLER_CONFIG = {
    'delay': 2.0,
    'timeout': 15,
    'batch_size': 50,
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ==================== 数据库操作 ====================
class DatabaseManager:
    def __init__(self, config: Dict):
        self.config = config
        db_url = f"mysql+pymysql://{config['user']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}?charset=utf8mb4"
        self.engine = create_engine(db_url, pool_size=10, max_overflow=20, echo=False)

    def test_connection(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.info("✅ 数据库连接成功！")
                return True
        except Exception as e:
            logger.error(f"❌ 数据库连接失败: {e}")
            return False

    def ensure_columns(self):
        try:
            with self.engine.connect() as conn:
                check_col = text("""
                    SELECT COUNT(*) 
                    FROM information_schema.columns 
                    WHERE table_schema = :db_name 
                    AND table_name = 'movies' 
                    AND column_name = 'maoyan_score'
                """)
                result = conn.execute(check_col, {'db_name': self.config['database']})
                col_exists = result.scalar() > 0

                if not col_exists:
                    logger.info("🔧 添加猫眼评分相关列...")
                    alter_sql = text("""
                        ALTER TABLE movies 
                        ADD COLUMN maoyan_score DECIMAL(3,1) DEFAULT NULL,
                        ADD COLUMN maoyan_id VARCHAR(50) DEFAULT NULL,
                        ADD COLUMN maoyan_updated_at TIMESTAMP NULL DEFAULT NULL
                    """)
                    conn.execute(alter_sql)
                    conn.commit()
                    logger.info("✅ 列添加成功")
                else:
                    logger.info("✅ 猫眼评分列已存在")
                return True
        except Exception as e:
            logger.error(f"❌ 初始化失败: {e}")
            return False

    def get_movies_to_update(self, limit: int = 50) -> List[Dict]:
        sql = text("""
            SELECT id, title, release_date, vote_average as tmdb_score
            FROM movies 
            WHERE (maoyan_score IS NULL OR maoyan_score = 0)
            AND title IS NOT NULL AND title != ''
            ORDER BY id 
            LIMIT :limit
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(sql, {'limit': limit})
                movies = []
                for row in result:
                    movies.append({
                        'id': row[0],
                        'title': row[1],
                        'release_date': str(row[2]) if row[2] else None,
                        'tmdb_score': float(row[3]) if row[3] else None
                    })
                logger.info(f"📥 获取到 {len(movies)} 部待更新电影")
                return movies
        except Exception as e:
            logger.error(f"❌ 获取电影列表失败: {e}")
            return []

    def update_score(self, movie_id: int, maoyan_score: float, maoyan_id: str = None):
        sql = text("""
            UPDATE movies 
            SET maoyan_score = :score, 
                maoyan_id = :maoyan_id,
                maoyan_updated_at = NOW()
            WHERE id = :movie_id
        """)
        try:
            with self.engine.connect() as conn:
                conn.execute(sql, {
                    'score': maoyan_score,
                    'maoyan_id': maoyan_id,
                    'movie_id': movie_id
                })
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ 更新失败: {e}")
            return False


# ==================== 猫眼爬虫（修复版） ====================
class MaoyanSpider:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://maoyan.com/',
            'Cookie': 'ci=1; _lxsdk_cuid=18c8c3e8d15c8-0a7c6f7f3e5d4; _lxsdk=18c8c3e8d15c8-0a7c6f7f3e5d4; _lxsdk_s=18c8c3e8d15c8-0a7c6f7f3e5d4'
        })

    def search_movie(self, keyword: str) -> List[Dict]:
        """
        使用猫眼的搜索API（POST方式）
        """
        # 猫眼搜索API
        search_url = 'https://maoyan.com/ajax/search'

        # 尝试两种方式
        try:
            # 方式1: 使用ajax接口
            params = {'kw': keyword}
            headers = self.session.headers.copy()
            headers.update({
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': 'https://maoyan.com/'
            })

            response = self.session.get(search_url, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if 'movies' in data and data['movies']:
                    results = []
                    for movie in data['movies'][:5]:
                        results.append({
                            'id': str(movie.get('id', '')),
                            'title': movie.get('nm', '')
                        })
                    return results

            # 方式2: 如果ajax失败，尝试直接访问详情页（通过搜索建议）
            suggest_url = 'https://maoyan.com/ajax/suggest'
            params = {'kw': keyword}
            response = self.session.get(suggest_url, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if 'data' in data and data['data']:
                    results = []
                    for item in data['data'][:5]:
                        if 'id' in item and 'nm' in item:
                            results.append({
                                'id': str(item.get('id', '')),
                                'title': item.get('nm', '')
                            })
                    return results

            logger.warning(f"⚠️ 搜索无结果: {keyword}")
            return []

        except Exception as e:
            logger.error(f"❌ 搜索失败 {keyword}: {e}")
            return []

    def get_movie_score(self, movie_id: str) -> Optional[Dict]:
        """获取猫眼电影评分"""
        # 使用猫眼详情页API
        api_url = f'https://maoyan.com/ajax/filminfo?filmId={movie_id}'

        try:
            headers = self.session.headers.copy()
            headers.update({
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f'https://maoyan.com/film/{movie_id}'
            })

            response = self.session.get(api_url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    film_info = data.get('data', {})
                    score = film_info.get('sc', 0)
                    title = film_info.get('nm', '')

                    if score and score > 0:
                        logger.info(f"✅ 获取到评分: {title} - {score}分")
                        return {
                            'id': movie_id,
                            'title': title,
                            'score': float(score)
                        }

            # 如果API失败，尝试直接爬取页面
            page_url = f'https://maoyan.com/film/{movie_id}'
            response = self.session.get(page_url, timeout=10)
            response.encoding = 'utf-8'

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')

                # 从页面提取评分
                score_elem = soup.select_one('.score-num')
                if score_elem:
                    score_text = score_elem.text.strip()
                    score_match = re.search(r'(\d+\.?\d*)', score_text)
                    if score_match:
                        score = float(score_match.group(1))
                        title_elem = soup.select_one('.movie-brief-container h1')
                        title = title_elem.text.strip() if title_elem else None

                        logger.info(f"✅ 获取到评分: {title} - {score}分")
                        return {
                            'id': movie_id,
                            'title': title,
                            'score': score
                        }

            logger.warning(f"⚠️ 未找到评分: {movie_id}")
            return None

        except Exception as e:
            logger.error(f"❌ 获取评分失败 {movie_id}: {e}")
            return None


# ==================== 主程序 ====================
class MaoyanUpdater:
    def __init__(self):
        self.db = DatabaseManager(MYSQL_CONFIG)
        self.spider = MaoyanSpider()
        self.stats = {'success': 0, 'failed': 0, 'not_found': 0}

    def process_movie(self, movie: Dict) -> bool:
        try:
            logger.info(f"\n📽️ 处理: {movie['title']}")

            # 搜索
            search_results = self.spider.search_movie(movie['title'])

            if not search_results:
                logger.warning(f"❌ 猫眼未找到: {movie['title']}")
                self.stats['not_found'] += 1
                return False

            # 匹配
            maoyan_movie = search_results[0]
            logger.info(f"🎯 匹配到: {maoyan_movie['title']} (ID: {maoyan_movie['id']})")

            # 获取评分
            time.sleep(CRAWLER_CONFIG['delay'])
            score_data = self.spider.get_movie_score(maoyan_movie['id'])

            if score_data and score_data.get('score'):
                success = self.db.update_score(
                    movie_id=movie['id'],
                    maoyan_score=score_data['score'],
                    maoyan_id=maoyan_movie['id']
                )
                if success:
                    self.stats['success'] += 1
                    logger.info(f"✅ 更新成功: {movie['title']} -> {score_data['score']}分")
                else:
                    self.stats['failed'] += 1
                return success
            else:
                logger.warning(f"⚠️ 未获取到评分: {movie['title']}")
                self.stats['failed'] += 1
                return False

        except Exception as e:
            logger.error(f"💥 处理失败: {e}")
            self.stats['failed'] += 1
            return False

    def run(self, batch_size: int = 10):
        logger.info("=" * 60)
        logger.info("🚀 猫眼评分更新程序启动")
        logger.info("=" * 60)

        if not self.db.test_connection():
            return

        if not self.db.ensure_columns():
            return

        movies = self.db.get_movies_to_update(limit=batch_size)

        if not movies:
            logger.info("🎉 所有电影已更新完毕！")
            self.show_stats()
            return

        for idx, movie in enumerate(movies, 1):
            self.process_movie(movie)
            time.sleep(1)

        self.show_stats()

    def show_stats(self):
        logger.info("\n" + "=" * 60)
        logger.info("📊 更新统计")
        logger.info("=" * 60)
        logger.info(f"✅ 成功: {self.stats['success']}")
        logger.info(f"❌ 失败: {self.stats['failed']}")
        logger.info(f"🔍 未找到: {self.stats['not_found']}")


# ==================== 测试 ====================
def test_single_movie():
    logger.info("🧪 测试模式")
    spider = MaoyanSpider()

    title = input("请输入电影名称 (直接回车测试'流浪地球2'): ").strip()
    if not title:
        title = "流浪地球2"

    print(f"\n🔍 搜索: {title}")
    results = spider.search_movie(title)

    if results:
        print(f"\n📋 搜索结果:")
        for r in results:
            print(f"   - {r['title']} (ID: {r['id']})")

        movie_id = results[0]['id']
        print(f"\n📊 获取评分: {movie_id}")
        score_data = spider.get_movie_score(movie_id)
        if score_data:
            print(f"✅ 评分: {score_data['title']} - {score_data['score']}分")
        else:
            print("❌ 未获取到评分")
    else:
        print("❌ 未找到电影")


if __name__ == "__main__":
    import sys

    print("""
    ╔═══════════════════════════════════════════╗
    ║   猫眼评分更新工具 v2.0 (修复版)         ║
    ║   使用猫眼AJAX API                       ║
    ╚═══════════════════════════════════════════╝
    """)

    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        test_single_movie()
    else:
        try:
            updater = MaoyanUpdater()
            batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 10
            updater.run(batch_size=batch_size)
        except KeyboardInterrupt:
            logger.info("\n⚠️ 用户中断")
        except Exception as e:
            logger.error(f"💥 程序异常: {e}")
            import traceback

            traceback.print_exc()
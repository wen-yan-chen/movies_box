import ssl
import certifi
import urllib3
import warnings
import pymysql
import requests
import time
import json
from typing import List, Dict, Optional

# ===== 禁用 SSL 验证（所有方案都加上）=====
warnings.filterwarnings('ignore')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context

# 创建一个自定义的 Session，禁用 SSL
session = requests.Session()
session.verify = False

# ========== 配置 ==========
MYSQL_PASSWORD = '20060321'
TMDB_API_KEY = '3a7253d0014eca94a6d059916e2fc186'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'
DELAY = 0.2
SEARCH_DELAY = 0.1


def get_db_connection():
    return pymysql.connect(
        host='127.0.0.1',
        user='root',
        password=MYSQL_PASSWORD,
        database='movie_db',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30
    )


def get_movies_without_cast(limit: int = 50) -> List[Dict]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 片名, 年份
            FROM tmdb_movies 
            WHERE (演员 IS NULL OR 演员 = '' OR 演员 = '[]')
            LIMIT %s
        """, (limit,))
        return cursor.fetchall()
    except Exception as e:
        print(f"查询数据库失败: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def search_movie_tmdb_id(title: str, year: float) -> Optional[int]:
    """通过片名和年份搜索 TMDB ID"""
    year_int = int(year) if year else None

    url = f"{TMDB_BASE_URL}/search/movie"
    params = {
        'api_key': TMDB_API_KEY,
        'query': title,
        'language': 'zh-CN'
    }
    if year_int:
        params['year'] = year_int

    try:
        # 使用自定义 session
        response = session.get(url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            if results:
                if year_int:
                    for r in results:
                        if r.get('release_date', '').startswith(str(year_int)):
                            return r.get('id')
                return results[0].get('id')
        return None
    except Exception as e:
        print(f"  搜索失败: {e}")
        return None


def get_movie_cast(tmdb_id: int) -> Optional[List[Dict]]:
    """从 TMDB API 获取电影演员列表"""
    url = f"{TMDB_BASE_URL}/movie/{tmdb_id}/credits"
    params = {
        'api_key': TMDB_API_KEY,
        'language': 'zh-CN'
    }

    try:
        # 使用自定义 session
        response = session.get(url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            cast = data.get('cast', [])[:10]
            result = []
            for actor in cast:
                result.append({
                    'name': actor.get('name', ''),
                    'character': actor.get('character', ''),
                    'profile_path': actor.get('profile_path', '')
                })
            return result
        else:
            print(f"  请求失败: TMDB ID {tmdb_id}, 状态码 {response.status_code}")
            return None
    except Exception as e:
        print(f"  获取演员信息失败: {e}")
        return None


def update_movie_cast(title: str, year: float, cast_data: List[Dict]) -> bool:
    conn = None
    cursor = None
    try:
        cast_json = json.dumps(cast_data, ensure_ascii=False)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tmdb_movies 
            SET 演员 = %s 
            WHERE 片名 = %s AND 年份 = %s
        """, (cast_json, title, year))
        return True
    except Exception as e:
        print(f"  更新数据库失败: {e}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def main():
    print("=" * 60)
    print("开始批量获取演员信息（通过片名+年份搜索）")
    print("=" * 60)

    movies = get_movies_without_cast(2000)
    total = len(movies)
    print(f"共找到 {total} 部电影缺少演员数据")

    if total == 0:
        print("所有电影已有演员信息，无需处理")
        return

    success_count = 0
    fail_count = 0
    search_fail_count = 0

    for idx, movie in enumerate(movies, 1):
        title = movie['片名']
        year = movie['年份']

        print(f"\n[{idx}/{total}] 处理: {title} ({year})")

        print(f"  - 正在搜索 TMDB ID...")
        tmdb_id = search_movie_tmdb_id(title, year)
        time.sleep(SEARCH_DELAY)

        if not tmdb_id:
            print(f"  ❌ 未找到 TMDB ID，跳过")
            search_fail_count += 1
            continue

        print(f"  - 找到 TMDB ID: {tmdb_id}")

        print(f"  - 正在获取演员信息...")
        cast_data = get_movie_cast(tmdb_id)

        if cast_data is not None and len(cast_data) > 0:
            if update_movie_cast(title, year, cast_data):
                print(f"  ✅ 成功保存 {len(cast_data)} 位演员")
                success_count += 1
            else:
                fail_count += 1
        else:
            print(f"  ⚠️ 未获取到演员信息")
            fail_count += 1

        time.sleep(DELAY)

    print("\n" + "=" * 60)
    print(f"处理完成！")
    print(f"  ✅ 成功: {success_count}")
    print(f"  ❌ 失败: {fail_count}")
    print(f"  🔍 未找到 TMDB ID: {search_fail_count}")
    print("=" * 60)


if __name__ == '__main__':
    main()
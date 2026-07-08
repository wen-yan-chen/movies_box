import pymysql
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from deep_translator import GoogleTranslator
import os
import time
import hashlib
from functools import lru_cache, wraps
from threading import Lock
import random
import json
import urllib.parse
from dbutils.pooled_db import PooledDB
import requests
import math
from datetime import datetime
app = Flask(__name__)
CORS(app)

# ========== 配置 ==========
MYSQL_PASSWORD = '20060321'
CACHE_TIMEOUT = 300
FILTER_CACHE_TIMEOUT = 3600
MAX_PER_PAGE = 50
DEBUG_MODE = False

# ========== 翻译器 ==========
translator = GoogleTranslator(source='auto', target='zh-CN')


def translate_text(text):
    """翻译文本到中文"""
    if not text or text == '暂无简介':
        return text
    try:
        if any('\u4e00' <= char <= '\u9fff' for char in text):
            return text
        if len(text) > 2000:
            text = text[:2000]
        translated = translator.translate(text)
        return translated
    except Exception as e:
        print(f"翻译失败: {e}")
        return text


def translate_title(title):
    """翻译电影名到中文"""
    if not title:
        return title
    try:
        if any('\u4e00' <= char <= '\u9fff' for char in title):
            return title
        translated = translator.translate(title)
        return translated
    except Exception as e:
        print(f"翻译标题失败: {e}")
        return title


# ========== 数据库连接池 ==========
pool = PooledDB(
    creator=pymysql,
    maxconnections=20,
    mincached=3,
    maxcached=10,
    blocking=True,
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


def get_db_connection():
    """从连接池获取数据库连接"""
    return pool.connection()


INVALID_GENRES = ['', ' ', '冒', '?', '未知', 'null', 'None']


# ========== 缓存系统 ==========
class CacheManager:
    def __init__(self):
        self._cache = {}
        self._lock = Lock()

    def get(self, key):
        with self._lock:
            if key in self._cache:
                data = self._cache[key]
                if data['expire'] > time.time():
                    return data['data']
                else:
                    del self._cache[key]
            return None

    def set(self, key, data, timeout=CACHE_TIMEOUT):
        with self._lock:
            self._cache[key] = {
                'data': data,
                'expire': time.time() + timeout
            }

    def clean(self):
        with self._lock:
            current_time = time.time()
            expired_keys = [k for k, v in self._cache.items() if v['expire'] < current_time]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

    def size(self):
        with self._lock:
            return len(self._cache)

    def clear_all(self):
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count


cache_manager = CacheManager()


def timing_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        if DEBUG_MODE:
            print(f"⏱️ {func.__name__} 执行时间: {(end - start) * 1000:.2f}ms")
        return result

    return wrapper


@app.route('/')
@app.route('/<path:filename>')
def serve_static(filename='index.html'):
    return send_from_directory(os.getcwd(), filename)


@app.route('/api/movies', methods=['GET'])
@timing_decorator
def get_movies():
    genres_param = request.args.get('genres', '')
    years_param = request.args.get('years', '')
    sort_param = request.args.get('sort', 'rating')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 24, type=int)

    per_page = min(per_page, MAX_PER_PAGE)
    page = max(page, 1)

    selected_genres = [g.strip() for g in genres_param.split(',') if g.strip()]
    selected_years = []
    if years_param.strip():
        for y in years_param.split(','):
            y = y.strip()
            if y:
                try:
                    selected_years.append(int(float(y)))
                except ValueError:
                    pass

    cache_key = None
    if page == 1 and not selected_genres and not selected_years:
        cache_key = f"movies_{sort_param}_{per_page}"
        cached_data = cache_manager.get(cache_key)
        if cached_data:
            return jsonify(cached_data)

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        base_sql = """
            SELECT 
                CONCAT(片名, '_', 年份) AS id,
                片名 AS title,
                年份 AS year,
                评分 AS vote_average,
                票房 AS revenue,
                上映日期 AS release_date,
                类型_标准化 AS genres,
                poster_url AS poster_path
            FROM tmdb_movies
            WHERE 1=1
        """
        params = []

        if selected_years:
            placeholders = ','.join(['%s'] * len(selected_years))
            base_sql += f" AND 年份 IN ({placeholders})"
            params.extend(selected_years)

        if selected_genres:
            genre_conditions = []
            for genre in selected_genres:
                genre_conditions.append("类型_标准化 LIKE %s")
                params.append(f"%{genre}%")
            base_sql += " AND (" + " OR ".join(genre_conditions) + ")"

        if sort_param == 'rating':
            base_sql += " ORDER BY 评分 DESC, 年份 DESC"
        elif sort_param == 'revenue':
            base_sql += " ORDER BY 票房 DESC, 评分 DESC"
        else:
            base_sql += " ORDER BY 年份 DESC, 评分 DESC"

        offset = (page - 1) * per_page
        base_sql += f" LIMIT {per_page} OFFSET {offset}"

        cursor.execute(base_sql, params)
        results = cursor.fetchall()

        total_count = None
        if page == 1 or len(results) < per_page:
            count_sql = "SELECT COUNT(*) as total FROM tmdb_movies WHERE 1=1"
            count_params = []
            if selected_years:
                placeholders = ','.join(['%s'] * len(selected_years))
                count_sql += f" AND 年份 IN ({placeholders})"
                count_params.extend(selected_years)
            if selected_genres:
                genre_conditions = []
                for genre in selected_genres:
                    genre_conditions.append("类型_标准化 LIKE %s")
                    count_params.append(f"%{genre}%")
                count_sql += " AND (" + " OR ".join(genre_conditions) + ")"
            cursor.execute(count_sql, count_params)
            total_count = cursor.fetchone()['total']
        else:
            total_count = (page - 1) * per_page + len(results) + per_page

        movie_list = []
        for row in results:
            cn_title = row['title']
            year = str(int(row['year'])) if row['year'] else "未知"
            genres_list = row['genres'].split(',') if row['genres'] else []

            poster_url = row['poster_path']
            if poster_url and poster_url.startswith('http://'):
                poster_url = poster_url.replace('http://', 'https://')

            movie_list.append({
                'id': row['id'],
                'title': cn_title,
                'original_title': row['title'],
                'rating': round(float(row['vote_average']), 1) if row['vote_average'] else 0,
                'revenue': row['revenue'] if row['revenue'] and row['revenue'] > 0 else 0,
                'year': year,
                'genres': [g.strip() for g in genres_list][:3],
                'poster': poster_url if poster_url else None
            })

        result = {
            'code': 200,
            'data': movie_list,
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_count + per_page - 1) // per_page if total_count else 1
        }

        if cache_key:
            cache_manager.set(cache_key, result, CACHE_TIMEOUT)

        return jsonify(result)

    except pymysql.Error as e:
        print(f"数据库错误: {e}")
        return jsonify({'code': 500, 'msg': f'数据库错误: {str(e)}'})
    except Exception as e:
        print(f"服务器错误: {e}")
        return jsonify({'code': 500, 'msg': f'服务器错误: {str(e)}'})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/api/filters', methods=['GET'])
@timing_decorator
def get_filters():
    cache_key = 'filters_data'
    cached_data = cache_manager.get(cache_key)
    if cached_data:
        return jsonify(cached_data)

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                (SELECT GROUP_CONCAT(DISTINCT 年份 ORDER BY 年份 DESC) 
                 FROM tmdb_movies 
                 WHERE 年份 IS NOT NULL AND 年份 > 1900) as years,
                (SELECT GROUP_CONCAT(DISTINCT 类型_标准化) 
                 FROM tmdb_movies 
                 WHERE 类型_标准化 IS NOT NULL AND TRIM(类型_标准化) != '') as genres_str
        """)
        row = cursor.fetchone()

        years = []
        if row and row['years']:
            year_list = row['years'].split(',')
            years = [int(float(y)) for y in year_list if y and y.strip()]
            years = sorted(list(set(years)), reverse=True)[:25]

        all_genres = set()
        if row and row['genres_str']:
            for g in row['genres_str'].split(','):
                g = g.strip()
                if g and g not in INVALID_GENRES:
                    all_genres.add(g)

        genres = sorted(list(all_genres))[:30]

        result = {
            'code': 200,
            'data': {
                'years': years,
                'genres': genres
            }
        }

        cache_manager.set(cache_key, result, FILTER_CACHE_TIMEOUT)
        return jsonify(result)

    except pymysql.Error as e:
        print(f"数据库错误: {e}")
        return jsonify({'code': 500, 'msg': f'数据库错误: {str(e)}'})
    except Exception as e:
        print(f"服务器错误: {e}")
        return jsonify({'code': 500, 'msg': f'服务器错误: {str(e)}'})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM tmdb_movies")
        total_movies = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(DISTINCT 年份) as total FROM tmdb_movies WHERE 年份 IS NOT NULL AND 年份 > 1900")
        total_years = cursor.fetchone()['total']

        cursor.execute("SELECT ROUND(AVG(评分), 2) as avg FROM tmdb_movies WHERE 评分 IS NOT NULL")
        avg_rating = cursor.fetchone()['avg'] or 0

        cursor.execute("SELECT MAX(年份) as latest FROM tmdb_movies WHERE 年份 IS NOT NULL")
        latest_year = cursor.fetchone()['latest'] or '-'

        return jsonify({
            'code': 200,
            'data': {
                'total_movies': total_movies,
                'total_years': total_years,
                'avg_rating': avg_rating,
                'latest_year': latest_year
            }
        })
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/api/rating-distribution', methods=['GET'])
def get_rating_distribution():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 评分 FROM tmdb_movies 
            WHERE 评分 IS NOT NULL AND 评分 > 0
        """)
        results = cursor.fetchall()
        return jsonify({'code': 200, 'data': results})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/api/rating-distribution-grouped', methods=['GET'])
@timing_decorator
def get_rating_distribution_grouped():
    cache_key = 'rating_distribution_grouped'
    cached_data = cache_manager.get(cache_key)
    if cached_data:
        return jsonify(cached_data)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 评分 
            FROM tmdb_movies 
            WHERE 评分 IS NOT NULL AND 评分 > 0
        """)
        results = cursor.fetchall()

        rating_count = {}
        for row in results:
            rating = row['评分']
            rounded = round(rating * 2) / 2
            key = str(rounded)
            rating_count[key] = rating_count.get(key, 0) + 1

        sorted_ratings = sorted(rating_count.items(), key=lambda x: float(x[0]))

        result_data = [{'rating': k, 'count': v} for k, v in sorted_ratings]

        result = {
            'code': 200,
            'data': result_data
        }

        cache_manager.set(cache_key, result, FILTER_CACHE_TIMEOUT)
        return jsonify(result)

    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/api/genre-distribution', methods=['GET'])
@timing_decorator
def get_genre_distribution():
    cache_key = 'genre_distribution_single'
    cached_data = cache_manager.get(cache_key)
    if cached_data:
        return jsonify(cached_data)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 类型_标准化 
            FROM tmdb_movies
            WHERE 类型_标准化 IS NOT NULL AND TRIM(类型_标准化) != ''
        """)
        results = cursor.fetchall()

        genre_count = {}
        for row in results:
            genres = row['类型_标准化'].split(',')
            for g in genres:
                g = g.strip()
                if g and g not in INVALID_GENRES:
                    genre_count[g] = genre_count.get(g, 0) + 1

        sorted_genres = sorted(genre_count.items(), key=lambda x: x[1], reverse=True)
        result_data = [{'genre': k, 'count': v} for k, v in sorted_genres]

        result = {
            'code': 200,
            'data': result_data
        }

        cache_manager.set(cache_key, result, FILTER_CACHE_TIMEOUT)
        return jsonify(result)

    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/api/year-trend', methods=['GET'])
@timing_decorator
def get_year_trend():
    cache_key = 'year_trend'
    cached_data = cache_manager.get(cache_key)
    if cached_data:
        return jsonify(cached_data)

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                年份 AS year,
                COUNT(*) AS count
            FROM tmdb_movies
            WHERE 年份 IS NOT NULL AND 年份 > 1900
            GROUP BY 年份
            ORDER BY 年份 ASC
        """)
        results = cursor.fetchall()

        result = {
            'code': 200,
            'data': results
        }

        cache_manager.set(cache_key, result, FILTER_CACHE_TIMEOUT)
        return jsonify(result)

    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ========== 票房趋势接口（按年份从近到远排序） ==========
@app.route('/api/revenue-trend', methods=['GET'])
@timing_decorator
def get_revenue_trend():
    """获取每年平均每部电影票房（按年份从近到远排序）"""
    cache_key = 'revenue_trend'
    cached_data = cache_manager.get(cache_key)
    if cached_data:
        return jsonify(cached_data)

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                年份 AS year,
                COUNT(*) AS movie_count,
                AVG(票房) AS avg_revenue,
                SUM(票房) AS total_revenue
            FROM tmdb_movies
            WHERE 年份 IS NOT NULL 
              AND 年份 > 1900 
              AND 票房 IS NOT NULL 
              AND 票房 > 0
            GROUP BY 年份
            HAVING COUNT(*) >= 3
            ORDER BY year DESC
        """)
        results = cursor.fetchall()

        formatted_results = []
        for row in results:
            formatted_results.append({
                'year': int(row['year']),
                'movie_count': row['movie_count'],
                'avg_revenue': round(float(row['avg_revenue']), 2) if row['avg_revenue'] else 0,
                'total_revenue': float(row['total_revenue']) if row['total_revenue'] else 0
            })

        result = {
            'code': 200,
            'data': formatted_results
        }

        cache_manager.set(cache_key, result, FILTER_CACHE_TIMEOUT)
        return jsonify(result)

    except Exception as e:
        print(f"获取票房趋势失败: {e}")
        return jsonify({'code': 500, 'msg': str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ========== 电影详情接口 ==========
@app.route('/api/movie/<path:movie_id>', methods=['GET'])
@timing_decorator
def get_movie_detail(movie_id):
    cache_key = f'movie_detail_{movie_id}'
    cached_data = cache_manager.get(cache_key)
    if cached_data:
        return jsonify(cached_data)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        decoded_id = urllib.parse.unquote(movie_id)
        decoded_id = decoded_id.replace('+', ' ')
        parts = decoded_id.rsplit('_', 1)

        if len(parts) != 2:
            return jsonify({'code': 400, 'msg': f'无效的电影ID格式: {decoded_id}'})

        title = parts[0].strip()
        year_str = parts[1].strip()

        try:
            year = float(year_str)
        except ValueError:
            return jsonify({'code': 400, 'msg': f'无效的年份格式: {year_str}'})

        cursor.execute("""
            SELECT 
                片名 AS title,
                片名 AS original_title,
                年份 AS year,
                上映日期 AS release_date,
                预算 AS budget,
                票房 AS revenue,
                片长 AS runtime,
                评分 AS vote_average,
                类型_标准化 AS genres,
                简介 AS overview,
                poster_url AS poster_path,
                演员 AS actors
            FROM tmdb_movies
            WHERE 片名 = %s AND 年份 = %s
        """, (title, year))

        row = cursor.fetchone()

        if not row:
            cursor.execute("""
                SELECT 
                    片名 AS title,
                    片名 AS original_title,
                    年份 AS year,
                    上映日期 AS release_date,
                    预算 AS budget,
                    票房 AS revenue,
                    片长 AS runtime,
                    评分 AS vote_average,
                    投票数 AS vote_count,
                    类型_标准化 AS genres,
                    简介 AS overview,
                    poster_url AS poster_path,
                    演员 AS actors
                FROM tmdb_movies
                WHERE LOWER(片名) LIKE LOWER(%s) AND 年份 = %s
                LIMIT 1
            """, (f'%{title}%', year))
            row = cursor.fetchone()

        if not row:
            return jsonify({'code': 404, 'msg': f'电影不存在: {title} ({int(year)})'})

        cn_title = translate_title(row['title'])
        overview = row['overview'] or '暂无简介'
        if overview and overview != '暂无简介':
            overview = row['overview'] or '暂无简介'

        actors = []
        if row.get('actors'):
            try:
                actors_data = json.loads(row['actors'])
                if isinstance(actors_data, list):
                    for a in actors_data[:10]:
                        if isinstance(a, dict) and 'name' in a:
                            actors.append(a['name'])
                        elif isinstance(a, str):
                            actors.append(a)
            except:
                pass

        revenue = row['revenue'] if row['revenue'] and row['revenue'] > 0 else 0

        result_data = {
            'id': movie_id,
            'title': cn_title,
            'original_title': row['original_title'] or row['title'],
            'year': int(row['year']) if row['year'] else None,
            'release_date': row['release_date'] if row['release_date'] else None,
            'budget': row['budget'] or 0,
            'revenue': revenue,
            'runtime': row['runtime'] or 0,
            'vote_average': round(float(row['vote_average']), 1) if row['vote_average'] else 0,
            'vote_count': row['vote_count'] or 0,
            'genres': [g.strip() for g in row['genres'].split(',')] if row['genres'] else [],
            'overview': overview,
            'poster': row['poster_path'] if row['poster_path'] else None,
            'actors': actors
        }

        result = {
            'code': 200,
            'data': result_data
        }

        cache_manager.set(cache_key, result, 3600)
        return jsonify(result)

    except pymysql.Error as e:
        print(f"数据库错误: {e}")
        return jsonify({'code': 500, 'msg': f'数据库错误: {str(e)}'})
    except Exception as e:
        print(f"服务器错误: {e}")
        return jsonify({'code': 500, 'msg': f'服务器错误: {str(e)}'})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ========== 关键词接口 ==========
@app.route('/api/movie/<path:movie_id>/keywords', methods=['GET'])
@timing_decorator
def get_movie_keywords(movie_id):
    import urllib.parse

    cache_key = f'movie_keywords_{movie_id}'
    cached_data = cache_manager.get(cache_key)
    if cached_data:
        return jsonify(cached_data)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        decoded_id = urllib.parse.unquote(movie_id)
        decoded_id = decoded_id.replace('+', ' ')
        parts = decoded_id.rsplit('_', 1)

        if len(parts) != 2:
            return jsonify({'code': 400, 'msg': f'无效的电影ID格式: {decoded_id}'})

        title = parts[0].strip()
        year_str = parts[1].strip()

        try:
            year = float(year_str)
        except ValueError:
            return jsonify({'code': 400, 'msg': f'无效的年份格式: {year_str}'})

        cursor.execute("""
            SELECT 
                片名 AS title, 
                片名 AS original_title,
                简介 AS overview, 
                类型_标准化 AS genres,
                评分 AS vote_average
            FROM tmdb_movies
            WHERE 片名 = %s AND 年份 = %s
        """, (title, year))

        row = cursor.fetchone()

        if not row:
            cursor.execute("""
                SELECT 
                    片名 AS title, 
                    片名 AS original_title,
                    简介 AS overview, 
                    类型_标准化 AS genres,
                    评分 AS vote_average
                FROM tmdb_movies
                WHERE LOWER(片名) LIKE LOWER(%s) AND 年份 = %s
                LIMIT 1
            """, (f'%{title}%', year))
            row = cursor.fetchone()

        if row:
            keywords = generate_keywords_from_movie(row['title'], row['genres'] or '', row['overview'] or '')
        else:
            keywords = generate_default_keywords()

        result = {
            'code': 200,
            'data': keywords
        }

        cache_manager.set(cache_key, result, 86400)
        return jsonify(result)

    except Exception as e:
        print(f"生成关键词失败: {e}")
        keywords = generate_default_keywords()
        return jsonify({'code': 200, 'data': keywords})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def generate_keywords_from_movie(title, genres, overview):
    keywords = []

    if genres:
        for g in genres.split(','):
            g = g.strip()
            if g and g not in keywords and len(g) >= 2:
                keywords.append(g)

    if overview:
        common_words = ['爱情', '冒险', '奇幻', '科幻', '悬疑', '喜剧', '悲剧', '复仇', '英雄',
                        '战争', '和平', '自由', '梦想', '勇气', '希望', '命运', '选择', '成长',
                        '家庭', '友情', '背叛', '救赎', '正义', '邪恶', '未来', '过去', '现在',
                        '动作', '惊悚', '犯罪', '灾难', '神话', '魔法', '怪兽', '外星', '穿越',
                        '经典', '视觉', '感动', '震撼', '创新', '艺术', '史诗', '浪漫', '黑暗',
                        '悬疑', '推理', '侦探', '神秘', '灵异', '恐怖', '血腥', '暴力', '温情',
                        '励志', '治愈', '青春', '校园', '职场', '爱情片', '动作片', '科幻片']
        for word in common_words:
            if word in overview and word not in keywords:
                keywords.append(word)

    # 只返回前10个最匹配的关键词
    return keywords[:10]


def generate_default_keywords():
    return ['电影', '精彩', '推荐', '经典', '视觉', '剧情', '演技', '感动', '震撼', '创新']


@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    count = cache_manager.clear_all()
    return jsonify({'code': 200, 'msg': f'已清除 {count} 个缓存'})


@app.route('/api/cache/status', methods=['GET'])
def cache_status():
    return jsonify({
        'code': 200,
        'cache_size': cache_manager.size(),
        'debug_mode': DEBUG_MODE
    })


# ========== 智能体推荐系统（简化版） ==========
import requests
import json
import math
import random
from datetime import datetime

# 硅基流动配置
SILICONFLOW_API_KEY = "sk-gqlddjvusikanwvvszouerpojzhpqhouwzodwjzmwdigvqil"
SILICONFLOW_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-ai/DeepSeek-V3"


def call_deepseek_api(user_message):
    """调用硅基流动 DeepSeek API 解析用户意图"""

    system_prompt = """你是一个电影推荐和票房预测助手。用户会描述他们的需求。
请从用户的需求中提取以下信息，并以 JSON 格式返回（只返回JSON，不要有其他内容）：

{
    "intent": "recommend" 或 "predict",
    "genres": ["类型1", "类型2"],
    "min_year": 年份,
    "max_year": 年份,
    "min_rating": 评分,
    "min_revenue": 票房,
    "keyword": "关键词",
    "similar_to": "电影名",
    "predict_title": "电影名",
    "predict_genre": "类型",
    "predict_budget": 预算金额(美元),
    "predict_year": 年份,
    "sort_by": "rating",
    "limit": 10,
    "recommendation_reason": "推荐理由"
}

规则：
1. 用户说"预测"时，intent 为 "predict"
2. 用户说"类似"、"像"时，填入 similar_to
3. 用户说"推荐"时，intent 为 "recommend"

只返回JSON，不要有其他内容。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 300,
        "stream": False
    }

    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        print(f"调用 DeepSeek API: {user_message}")
        response = requests.post(SILICONFLOW_API_URL, json=payload, headers=headers, timeout=30)

        if response.status_code != 200:
            print(f"API 错误: {response.status_code} - {response.text}")
            return None

        result = response.json()
        raw = result["choices"][0]["message"]["content"]

        # 清理 markdown
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        import re
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            cleaned = match.group()

        print(f"解析结果: {cleaned}")
        return json.loads(cleaned)

    except Exception as e:
        print(f"API 调用失败: {e}")
        return None


def fallback_parse(user_message):
    """备用解析"""
    result = {"intent": "recommend", "genres": [], "similar_to": None}

    if "预测" in user_message:
        result["intent"] = "predict"
        result["predict_year"] = 2027
        import re
        year_match = re.search(r'20\d{2}', user_message)
        if year_match:
            result["predict_year"] = int(year_match.group())
        result["recommendation_reason"] = f"为您预测{result['predict_year']}年电影票房"
        return result

    if "类似" in user_message or "像" in user_message:
        import re
        match = re.search(r'《(.+?)》', user_message)
        if match:
            result["similar_to"] = match.group(1)
            result["recommendation_reason"] = f"为您推荐类似《{result['similar_to']}》的电影"
            return result

    genres = ['动作', '喜剧', '科幻', '爱情', '恐怖', '悬疑', '奇幻', '冒险', '动画', '剧情']
    for g in genres:
        if g in user_message:
            result["genres"] = [g]
            result["recommendation_reason"] = f"为您推荐{g}电影"
            return result

    result["recommendation_reason"] = "为您推荐热门电影"
    return result


def predict_revenue_simple(genre=None, budget=None, year=None):
    """简化票房预测"""
    if budget is None or budget <= 0:
        budget = 20000000
    if year is None:
        year = 2027
    if genre is None or genre == '':
        genre = '剧情'

    multipliers = {
        '动作': 1.8, '喜剧': 1.4, '科幻': 2.0, '爱情': 1.2,
        '恐怖': 1.5, '悬疑': 1.5, '奇幻': 1.9, '冒险': 1.6,
        '动画': 1.7, '剧情': 1.2, '犯罪': 1.3, '惊悚': 1.4
    }

    base = budget * 2.5
    genre_factor = multipliers.get(genre, 1.2)
    year_factor = 1 + (year - 2010) * 0.03
    random_factor = 0.85 + random.random() * 0.3

    predicted = base * genre_factor * year_factor * random_factor
    predicted = max(budget * 0.5, min(budget * 15, predicted))

    return predicted


@app.route('/api/agent/recommend', methods=['POST'])
@timing_decorator
def agent_recommend():
    """智能体推荐电影接口"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'code': 400, 'msg': '请求数据为空'}), 400

        user_message = data.get('message', '').strip()
        if not user_message:
            return jsonify({'code': 400, 'msg': '请输入您想看的电影类型或需求'}), 400

        # 调用 API 解析
        parsed = call_deepseek_api(user_message)
        if not parsed:
            parsed = fallback_parse(user_message)

        if not parsed:
            return jsonify({'code': 500, 'msg': '无法解析您的需求，请换个说法'}), 500

        intent = parsed.get('intent', 'recommend')
        print(f"最终意图: {intent}, 解析结果: {parsed}")

        # ===== 预测模式 =====
        if intent == 'predict':
            genre = parsed.get('predict_genre')
            budget = parsed.get('predict_budget')
            year = parsed.get('predict_year')

            if not year:
                year = 2027

            if not genre:
                genre_keywords = ['动作', '喜剧', '科幻', '爱情', '恐怖', '悬疑', '奇幻', '冒险', '动画', '剧情',
                                  '犯罪', '惊悚']
                for g in genre_keywords:
                    if g in user_message:
                        genre = g
                        break
                if not genre:
                    genre = '剧情'

            if budget and budget < 1000000:
                budget = budget * 1000000

            if not budget or budget <= 0:
                default_budgets = {
                    '科幻': 80000000, '动作': 60000000, '奇幻': 70000000,
                    '冒险': 50000000, '动画': 40000000, '喜剧': 30000000,
                    '爱情': 25000000, '悬疑': 30000000, '惊悚': 25000000,
                    '恐怖': 20000000, '剧情': 20000000, '犯罪': 30000000
                }
                budget = default_budgets.get(genre, 20000000)

            predicted = predict_revenue_simple(genre, budget, year)
            roi = ((predicted - budget) / budget) * 100

            if predicted < 10000000:
                risk = '较低，建议控制成本'
            elif predicted < 50000000:
                risk = '中等，有盈利空间'
            elif predicted < 200000000:
                risk = '良好，有望成为热门'
            else:
                risk = '优秀，有望成为爆款'

            result = {
                'type': 'prediction',
                'title': f'{year}年{genre}电影',
                'genre': genre,
                'budget': budget,
                'year': year,
                'predicted_revenue': round(predicted, 2),
                'predicted_revenue_m': round(predicted / 1000000, 2),
                'roi': round(roi, 1),
                'risk': risk,
                'detail': f'基于市场数据预测，该{genre}电影预计票房约 ${round(predicted / 1000000, 2)}M'
            }

            return jsonify({
                'code': 200,
                'data': {
                    'message': f'为您预测{year}年{genre}电影票房',
                    'prediction': result,
                    'movies': [],
                    'count': 0,
                    'is_prediction': True
                }
            })

        # ===== 推荐模式 =====
        conditions = []
        params = []

        # 处理"类似XX"的推荐
        similar_movie = parsed.get('similar_to')
        if similar_movie:
            conn = None
            cursor = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT 类型_标准化, 片名, 评分, 年份
                    FROM tmdb_movies
                    WHERE 片名 LIKE %s OR 片名 LIKE %s
                    LIMIT 1
                """, (f'%{similar_movie}%', f'{similar_movie}%'))
                ref_movie = cursor.fetchone()

                if ref_movie:
                    ref_genres = []
                    try:
                        if ref_movie.get('类型_标准化'):
                            if isinstance(ref_movie['类型_标准化'], str):
                                ref_genres = [g.strip() for g in ref_movie['类型_标准化'].split(',') if g.strip()]
                    except:
                        pass

                    if ref_genres:
                        genre_conditions = []
                        for genre in ref_genres[:2]:
                            if genre and genre.strip():
                                genre_conditions.append("类型_标准化 LIKE %s")
                                params.append(f"%{genre}%")
                        if genre_conditions:
                            conditions.append(f"({' OR '.join(genre_conditions)})")

                    if ref_movie.get('评分'):
                        conditions.append("评分 >= %s")
                        params.append(max(0, float(ref_movie['评分']) - 1.5))

                    if ref_movie.get('年份'):
                        year_val = int(ref_movie['年份'])
                        conditions.append("年份 BETWEEN %s AND %s")
                        params.append(year_val - 3)
                        params.append(year_val + 3)

                    conditions.append("片名 NOT LIKE %s")
                    params.append(f'%{similar_movie}%')

                    parsed['sort_by'] = 'rating'
            except Exception as e:
                print(f"相似电影查询失败: {e}")
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

        # 类型筛选
        if parsed.get('genres') and len(parsed['genres']) > 0 and not similar_movie:
            genre_conditions = []
            for genre in parsed['genres']:
                if genre and genre.strip():
                    genre_conditions.append("类型_标准化 LIKE %s")
                    params.append(f"%{genre}%")
            if genre_conditions:
                conditions.append(f"({' OR '.join(genre_conditions)})")

        # 年份
        if parsed.get('min_year') and not similar_movie:
            conditions.append("年份 >= %s")
            params.append(int(parsed['min_year']))
        if parsed.get('max_year') and not similar_movie:
            conditions.append("年份 <= %s")
            params.append(int(parsed['max_year']))

        # 评分
        if parsed.get('min_rating') and not similar_movie:
            conditions.append("评分 >= %s")
            params.append(float(parsed['min_rating']))

        # 票房
        if parsed.get('min_revenue'):
            conditions.append("票房 >= %s")
            params.append(float(parsed['min_revenue']))

        # 关键词
        if parsed.get('keyword') and not similar_movie:
            conditions.append("(片名 LIKE %s OR 简介 LIKE %s)")
            keyword = f"%{parsed['keyword']}%"
            params.extend([keyword, keyword])

        if not conditions:
            conditions.append("1=1")

        where_clause = " AND ".join(conditions)
        sort_by = parsed.get('sort_by', 'rating')
        sort_mapping = {
            'rating': '评分 DESC, 年份 DESC',
            'revenue': '票房 DESC, 评分 DESC',
            'year': '年份 DESC, 评分 DESC'
        }
        order_clause = sort_mapping.get(sort_by, '评分 DESC')
        limit = min(parsed.get('limit', 10), 24)

        query = f"""
            SELECT 
                片名 AS title,
                年份 AS year,
                评分 AS vote_average,
                票房 AS revenue,
                类型_标准化 AS genres,
                简介 AS overview,
                poster_url AS poster_path
            FROM tmdb_movies
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT %s
        """
        params.append(limit)

        print(f"执行查询: {query}")
        print(f"参数: {params}")

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = cursor.fetchall()

            movies = []
            for row in results:
                genres = []
                try:
                    if row.get('genres'):
                        if isinstance(row['genres'], str):
                            genres = [g.strip() for g in row['genres'].split(',') if g.strip()]
                except:
                    pass

                movie_id = f"{row['title']}_{int(row['year'])}" if row.get('year') else row['title']

                movies.append({
                    'id': movie_id,
                    'title': row['title'],
                    'year': int(row['year']) if row.get('year') else None,
                    'vote_average': float(row['vote_average']) if row.get('vote_average') else 0,
                    'revenue': int(row['revenue']) if row.get('revenue') and row['revenue'] > 0 else 0,
                    'genres': genres[:3] if genres else [],
                    'overview': row.get('overview') or '暂无简介',
                    'poster_path': row.get('poster_path') if row.get('poster_path') else None
                })

            return jsonify({
                'code': 200,
                'data': {
                    'message': parsed.get('recommendation_reason', '根据您的需求为您推荐以下电影'),
                    'movies': movies,
                    'count': len(movies),
                    'is_prediction': False
                }
            })

        except pymysql.Error as e:
            print(f"数据库错误: {e}")
            return jsonify({'code': 500, 'msg': f'数据库查询失败: {str(e)}'}), 500
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    except Exception as e:
        print(f"智能推荐出错: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'code': 500, 'msg': f'服务器错误: {str(e)}'}), 500
if __name__ == '__main__':
    print("=" * 50)
    print("电影评估系统后端已启动")
    print("请访问: http://127.0.0.1:5000")
    print("=" * 50)

    app.run(
        debug=DEBUG_MODE,
        port=5000,
        host='127.0.0.1',
        threaded=True,
        use_reloader=False
    )
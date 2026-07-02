import requests
import mysql.connector
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ========== 请替换以下内容 ==========
API_KEY = "3a7253d0014eca94a6d059916e2fc186"
MYSQL_PASSWORD = "20060321"
# ====================================

POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"

# 带重试机制的 session
session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount('https://', adapter)

# 连接 MySQL
conn = mysql.connector.connect(
    host='127.0.0.1',
    user='root',
    password=MYSQL_PASSWORD,
    database='movie_db',
    charset='utf8mb4'
)
cursor = conn.cursor()

# ========== 修改年份范围：2002-2016 ==========
years = list(range(2008, 2017))  # 2002-2016

total_success = 0
total_fail = 0

for year in years:
    print(f"\n📊 开始处理 {year} 年的电影...")

    # 查询该年份没有海报的电影
    cursor.execute("""
        SELECT 片名, 年份 FROM tmdb_movies 
        WHERE 年份 = %s AND (poster_url IS NULL OR poster_url = '')
    """, (year,))

    movies = cursor.fetchall()

    if not movies:
        print(f"📌 {year} 年没有需要补海报的电影")
        continue

    print(f"📌 {year} 年共 {len(movies)} 部电影需要补海报")
    year_success = 0

    for title, movie_year in movies:
        # 搜索电影
        search_url = f"https://api.themoviedb.org/3/search/movie?api_key={API_KEY}&query={title}&language=zh-CN"

        try:
            search_response = session.get(search_url, timeout=15)
            search_data = search_response.json()

            if search_response.status_code == 200 and search_data.get('results'):
                movie_id = search_data['results'][0]['id']

                # 获取详情（含海报）
                detail_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={API_KEY}&language=zh-CN"
                detail_response = session.get(detail_url, timeout=15)
                detail_data = detail_response.json()

                if detail_response.status_code == 200:
                    poster_path = detail_data.get('poster_path')
                    if poster_path:
                        poster_url = POSTER_BASE_URL + poster_path

                        # 更新旧表的海报字段
                        update_sql = "UPDATE tmdb_movies SET poster_url = %s WHERE 片名 = %s AND 年份 = %s"
                        cursor.execute(update_sql, (poster_url, title, movie_year))
                        conn.commit()
                        year_success += 1
                        total_success += 1
                        print(f"  ✅ 更新成功: {title} ({movie_year})")
                    else:
                        total_fail += 1
                        print(f"  ⚠️ 无海报: {title} ({movie_year})")
                else:
                    total_fail += 1
            else:
                total_fail += 1
                print(f"  ⚠️ 搜索无结果: {title} ({movie_year})")

        except Exception as e:
            print(f"  ❌ 获取失败 {title}: {e}")
            total_fail += 1

        time.sleep(0.15)

    print(f"✅ {year} 年完成，成功: {year_success} 部")

print(f"\n🎉 全部完成！")
print(f"✅ 成功更新: {total_success} 张海报")
print(f"❌ 失败: {total_fail} 部")

cursor.close()
conn.close()
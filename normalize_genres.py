import pymysql
import re

# ========== 类型映射 ==========
GENRE_MAP = {
    'Action': '动作',
    'Adventure': '冒险',
    'Animation': '动画',
    'Comedy': '喜剧',
    'Crime': '犯罪',
    'Documentary': '纪录',
    'Drama': '剧情',
    'Family': '家庭',
    'Fantasy': '奇幻',
    'Foreign': '外国',
    'History': '历史',
    'Horror': '恐怖',
    'Music': '音乐',
    'Mystery': '悬疑',
    'Romance': '爱情',
    'Science Fiction': '科幻',
    'Thriller': '惊悚',
    'TV Movie': '电视电影',
    'War': '战争',
    'Western': '西部'
}

# ========== 数据库配置 ==========
MYSQL_PASSWORD = '20060321'


def normalize_genre(genre_str):
    """标准化类型：统一转中文，去重，排序"""
    if not genre_str:
        return ''

    # 按逗号分割
    parts = [g.strip() for g in genre_str.split(',') if g.strip()]

    # 翻译成中文
    chinese_parts = []
    for p in parts:
        if p in GENRE_MAP:
            chinese_parts.append(GENRE_MAP[p])
        elif p in GENRE_MAP.values():
            chinese_parts.append(p)
        else:
            # 如果不在映射里，保留原样
            chinese_parts.append(p)

    # 去重并排序
    unique = []
    for p in chinese_parts:
        if p not in unique:
            unique.append(p)

    return ', '.join(sorted(unique))


def main():
    conn = pymysql.connect(
        host='127.0.0.1',
        user='root',
        password=MYSQL_PASSWORD,
        database='movie_db',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    # 读取所有电影的类型
    cursor.execute("SELECT 片名, 类型 FROM tmdb_movies WHERE 类型 IS NOT NULL")
    rows = cursor.fetchall()

    print(f"📊 共 {len(rows)} 条数据需要处理")

    success_count = 0
    for row in rows:
        title = row['片名']
        raw_genre = row['类型']
        normalized = normalize_genre(raw_genre)

        # 更新数据库
        update_sql = "UPDATE tmdb_movies SET 类型_标准化 = %s WHERE 片名 = %s"
        cursor.execute(update_sql, (normalized, title))
        success_count += 1

        if success_count % 100 == 0:
            conn.commit()
            print(f"进度: {success_count}/{len(rows)}")

    conn.commit()
    print(f"✅ 完成！共处理 {success_count} 条数据")

    # 查看标准化后的类型分布
    cursor.execute("""
        SELECT 类型_标准化, COUNT(*) as cnt 
        FROM tmdb_movies 
        WHERE 类型_标准化 IS NOT NULL 
        GROUP BY 类型_标准化 
        ORDER BY cnt DESC 
        LIMIT 20
    """)
    results = cursor.fetchall()
    print("\n📊 标准化后的类型分布（前20）：")
    for r in results:
        print(f"  {r['类型_标准化']}: {r['cnt']}")

    cursor.close()
    conn.close()


if __name__ == '__main__':
    main()
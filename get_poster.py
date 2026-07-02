import requests
import mysql.connector
import time
import urllib.parse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_KEY = "3a7253d0014eca94a6d059916e2fc186"
MYSQL_PASSWORD = "20060321"
POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"

# ========== 要爬的电影列表 ==========
movie_list = [
    "Dragon Blade",
    "Taken 3",
    "Curse of the Golden Flower",
    "Black Water Transit",
    "Abandon",
    "Brokedown Palace",
    "The Possession",
    "Mrs. Winterbourne",
    "Straw Dogs",
    "The Hoax",
    "Stone Cold",
    "The Road",
    "Sheena",
    "Underclassman",
    "Say It Isn't So",
    "The World's Fastest Indian",
    "Tank Girl",
    "King's Ransom",
    "Blindness",
    "BloodRayne",
    "Carnage",
    "Where the Truth Lies",
    "Cirque du Soleil: Worlds Away",
    "Me and Orson Welles",
    "The Best Offer",
    "The Bad Lieutenant: Port of Call - New Orleans",
    "A Turtle's Tale: Sammy's Adventures",
    "Little White Lies",
    "The True Story of Puss 'n Boots",
    "Space Dogs",
    "The Counselor",
    "Ironclad",
    "Waterloo",
    "Kung Fu Jungle",
    "Red Sky",
    "Dangerous Liaisons",
    "On the Road",
    "Star Trek IV: The Voyage Home",
    "Rocky Balboa",
    "Footloose",
    "Old School",
    "The Fisher King",
    "I Still Know What You Did Last Summer",
    "Return to Me",
    "Zack and Miri Make a Porno",
    "Girl, Interrupted",
    "Win a Date with Tad Hamilton!",
    "Muppets from Space",
    "The Wiz",
    "Ready to Rumble",
    "Play It to the Bone",
    "I Don't Know How She Does It",
    "Piranha 3D",
    "Beyond the Sea",
    "Meet the Deedles",
    "The Thief and the Cobbler",
    "The Bridge of San Luis Rey",
    "Faster",
    "Howl's Moving Castle",
    "Zombieland",
    "The Waterboy",
    "The Empire Strikes Back",
    "Bad Boys",
    "The Naked Gun 2½: The Smell of Fear",
    "Final Destination",
    "The Ides of March",
    "Pitch Black",
    "Someone Like You...",
    "Her",
    "Joy Ride",
    "The Adventurer: The Curse of the Midas Box",
    "Anywhere But Here",
    "The Crew",
    "Haywire",
    "Jaws: The Revenge",
    "Marvin's Room",
    "The Longshots",
    "The End of the Affair",
    "Harley Davidson and the Marlboro Man",
    "In the Valley of Elah",
    "Ramanujan",
    "Out of Inferno",
    "Brazil",
    "Listening",
    "The Assassin",
    "The Lucky Ones",
    "A Tale of Three Cities",
    "Star Wars: Clone Wars: Volume 1",
    "Alien Zone",
    "Aimee & Jaguar",
    "The Brothers",
    "The Flower of Evil",
    "Once Upon a Time in the West",
    "Of Gods and Men",
    "Standard Operating Procedure",
    "City of God",
    "The Dead Girl",
    "Trippin'",
    "The Dress",
    "Mi America",
    "Return of the Living Dead 3",
    "Sublime",
    "Nine Queens",
    "#Horror",
    "Walking and Talking",
    "The Young Unknowns",
    "Dead Snow",
    "The Harvest (La Cosecha)",
    "Crazy Stone",
    "UnDivided",
    "Give Me Shelter",
    "A Fistful of Dollars",
    "Short Cut to Nirvana: Kumbh Mela",
    "Call + Response",
    "Theresa Is a Mother",
    "H.",
    "The Blood of My Brother: A Story of Death in Iraq",
    "The Work and The Story"
]
# ===================================

# 带重试的 session
session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount('https://', adapter)

conn = mysql.connector.connect(
    host='127.0.0.1',
    user='root',
    password=MYSQL_PASSWORD,
    database='movie_db',
    charset='utf8mb4'
)
cursor = conn.cursor()

print(f"📌 共 {len(movie_list)} 部电影，开始获取海报...")

success_count = 0
fail_count = 0

for title in movie_list:
    search_url = f"https://api.themoviedb.org/3/search/movie?api_key={API_KEY}&query={urllib.parse.quote(title)}&language=zh-CN"

    try:
        search_response = session.get(search_url, timeout=15)
        search_data = search_response.json()
        results = search_data.get('results', [])

        # 搜索不到时，尝试去掉副标题（冒号后面）
        if not results and ':' in title:
            simplified = title.split(':')[0].strip()
            search_url2 = f"https://api.themoviedb.org/3/search/movie?api_key={API_KEY}&query={urllib.parse.quote(simplified)}&language=zh-CN"
            search_response2 = session.get(search_url2, timeout=15)
            search_data2 = search_response2.json()
            results = search_data2.get('results', [])

        if results:
            movie_id = results[0]['id']

            detail_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={API_KEY}&language=zh-CN"
            detail_response = session.get(detail_url, timeout=15)
            detail_data = detail_response.json()

            if detail_response.status_code == 200:
                poster_path = detail_data.get('poster_path')
                if poster_path:
                    poster_url = POSTER_BASE_URL + poster_path
                    success_count += 1
                    update_sql = "UPDATE tmdb_movies_with_poster SET poster_url = %s WHERE 片名 = %s"
                    cursor.execute(update_sql, (poster_url, title))
                    conn.commit()
                    print(f"✅ 修复成功: {title}")
                else:
                    print(f"⚠️ 无海报: {title}")
                    fail_count += 1
            else:
                print(f"⚠️ 详情获取失败: {title}")
                fail_count += 1
        else:
            print(f"⚠️ 搜索无结果: {title}")
            fail_count += 1

    except Exception as e:
        print(f"❌ 获取失败 {title}: {e}")
        fail_count += 1

    time.sleep(0.3)

print(f"\n✅ 修复完成！成功: {success_count}，失败: {fail_count}")

cursor.close()
conn.close()
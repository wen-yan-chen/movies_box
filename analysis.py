import pandas as pd
from sqlalchemy import create_engine
import matplotlib.pyplot as plt
import seaborn as sns

# 设置中文显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# 连接 MySQL
engine = create_engine('mysql+pymysql://root:20060321@127.0.0.1:3306/movie_db')

# 读取数据
df = pd.read_sql('SELECT * FROM movies', con=engine)

print(f" 共 {len(df)} 部电影")
print(f" 年份范围：{df['年份'].min()} - {df['年份'].max()}")
print(f" 平均评分：{df['评分'].mean():.2f}")

# 1. 评分分布直方图
plt.figure(figsize=(10, 6))
plt.hist(df['评分'], bins=15, edgecolor='black', alpha=0.7)
plt.title('电影评分分布')
plt.xlabel('评分')
plt.ylabel('电影数量')
plt.savefig('评分分布图.png', dpi=300, bbox_inches='tight')
plt.show()

# 2. 各年份电影数量
year_counts = df['年份'].value_counts().sort_index()
plt.figure(figsize=(12, 6))
year_counts.plot(kind='bar')
plt.title('各年份电影数量分布')
plt.xlabel('年份')
plt.ylabel('电影数量')
plt.savefig('年份分布图.png', dpi=300, bbox_inches='tight')
plt.show()

# 3. 年份与评分的关系
plt.figure(figsize=(12, 6))
plt.scatter(df['年份'], df['评分'], alpha=0.6)
plt.title('年份与评分的关系')
plt.xlabel('年份')
plt.ylabel('评分')
plt.savefig('年份评分关系图.png', dpi=300, bbox_inches='tight')
plt.show()

print("✅ 图表已保存！")
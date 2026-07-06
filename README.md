# 电影票房数据可视化系统 (Movies-Box)

一个基于 Flask + MySQL + ECharts 的电影数据管理与可视化平台，集成 DeepSeek AI 智能助手，支持自然语言推荐与票房预测。


## 项目简介

在当今电影产业高速发展的背景下，猫眼、淘票票等票务平台积累了海量的电影票房、评分、评论等数据，这些信息蕴含着巨大的分析价值，但原始数据呈现分散、非结构化的特点，难以直接为行业从业者、研究者或普通观众提供直观的决策参考。

Movies-Box 通过整合 TMDB 全球影视库与猫眼中国票房数据，利用 ECharts 实现多维度可视化分析，并引入大语言模型，为用户提供自然语言驱动的智能推荐与票房预测服务，帮助用户更直观地理解电影市场规律。


## 核心功能

### 电影总览
- 卡片网格展示电影列表（海报、片名、评分、年份）
- 类型/年份多选筛选
- 按评分/票房排序切换
- 滚动触底无限加载 + 图片懒加载
- 电影详情弹窗（含词云图）

### 可视化分析

| 页面 | 图表类型 | 说明 |
|------|----------|------|
| 上映趋势 | 柱状图 + 折线图 | 各年份电影数量，蓝色渐变 |
| 票房趋势 | 柱状图 + 折线图 | 各年份平均票房，过滤无效数据 |
| 类型统计 | 环形图 + 柱状图 | 独立类型精确统计，显示全部类型 |
| 评分分布 | 横向条形图 | 按0.5分档聚合 |

### AI 智能助手
- 自然语言推荐：输入"推荐几部2020年后高分科幻片"即可获得结果
- 模糊语义理解：支持"类似《盗梦空间》"的推荐
- 票房预测：自动识别"预测"关键词，综合类型系数、预算规模、年份趋势输出量化参考
- 备用解析机制：API 不可用时自动降级到关键词匹配

### 交互体验
- 夜间模式（localStorage 持久化）
- 侧边栏拖拽调整宽度
- 图表自适应（ResizeObserver）
- 电影详情弹窗（模糊背景 + 词云图）


## 技术架构

| 层级 | 技术栈 | 说明 |
|------|--------|------|
| 前端 | HTML + Tailwind + ECharts | 电影总览 / 上映趋势 / 票房趋势 / 类型统计 / 评分分布 |
| 后端 | Flask + PyMySQL | 11个 RESTful API / 内存缓存 (TTL) / 连接池 (PooledDB) |
| 数据库 | MySQL | tmdb_movies (10,294条) |
| 数据源 | Kaggle / TMDB API / 猫眼 | 数据采集与反爬破解 |


## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | 原生 HTML + Tailwind CSS + ECharts 5 + Fetch API |
| 后端 | Python Flask + Flask-CORS |
| 数据库 | MySQL 8.0 + PyMySQL + DBUtils (连接池) |
| 数据源 | Kaggle API + TMDB API + 猫眼爬虫 |
| AI | 硅基流动 DeepSeek API |
| 版本控制 | Git + GitHub |


## 快速开始

### 环境要求
- Python 3.13+
- MySQL 8.0+
- 现代浏览器（Chrome 90+ / Firefox 88+ / Edge 90+）

### 安装步骤

```bash
git clone https://github.com/your-username/movies-box.git
cd movies-box
pip install -r requirements.txt
python app.py
```

访问 http://127.0.0.1:5000


## 项目结构


```text
movies-box/
├── analysis.py             # 数据分析脚本
├── app.py                  # Flask 后端主程序
├── fetch_cast.py           # 演职员数据爬虫
├── fetch_new_movies.py     # TMDB API 爬虫
├── get_poster.py           # 海报补全脚本
├── index.html              # 前端页面
├── maoyan_updater.py       # 猫眼数据更新脚本
├── normalize_genres.py     # 类型标准化脚本
└── test_api.py             # API 测试脚本

```


## 后端 API 接口


| 接口 | 方法 | 功能 | 缓存 |
|------|------|------|------|
| /api/movies | GET | 电影列表查询（筛选、排序、分页） | 5分钟 |
| /api/filters | GET | 获取类型/年份筛选项 | 1小时 |
| /api/year-trend | GET | 每年电影数量趋势 | 1小时 |
| /api/revenue-trend | GET | 每年平均票房趋势 | 1小时 |
| /api/stats | GET | 统计数据 | 无 |
| /api/rating-distribution-grouped | GET | 评分分布（0.5分档） | 1小时 |
| /api/genre-distribution | GET | 类型分布（独立类型统计） | 1小时 |
| /api/movie/{id} | GET | 电影详情 | 1小时 |
| /api/movie/{id}/keywords | GET | 电影关键词 | 24小时 |
| /api/cache/clear | POST | 清除缓存 | — |
| /api/cache/status | GET | 查看缓存状态 | — |



## 数据库设计

### 数据表结构 (tmdb_movies)


| 字段名 | 类型 | 说明 |
|--------|------|------|
| 片名 | longtext | 电影名称 |
| 上映日期 | longtext | 公映日期 |
| 预算 | bigint | 制作预算（美元） |
| 票房 | bigint | 全球票房收入（美元） |
| 片长 | double | 播放时长（分钟） |
| 评分 | double | TMDB综合评分（0-10） |
| 投票数 | bigint | 评分参与人数 |
| 类型 | longtext | 原始类型（中英文混杂） |
| 简介 | longtext | 剧情简介 |
| 年份 | double | 上映年份（已索引） |
| poster_url | longtext | 海报URL |
| 类型_标准化 | longtext | 标准化中文类型（逗号分隔） |
| 演员 | text | 演员信息（JSON数组） |


### 索引设计
- 年份 (BTREE)：优化年份趋势查询
- 评分 (BTREE)：优化按评分排序
- 票房 (BTREE)：优化按票房排序


## 数据资产

| 项目 | 详情 |
|------|------|
| 数据库 | MySQL（movie_db） |
| 主表 | tmdb_movies |
| 记录数 | 10,294 条 |
| 年份范围 | 2002 – 2026（24个年份） |
| 数据来源 | Kaggle TMDB 5000 + TMDB API + 猫眼爬虫 |


## 技术创新

### 1. 反爬破解
猫眼平台的票房、评分等数据在HTML源码中显示为乱码符号，通过自定义字体实现加密。采用"以形补数"的思路，解析woff字体文件比对字形坐标建立动态映射，无论编码如何变化都能准确还原真实数字，成功突破字体反爬、Cookie验证和IP频率限制三重屏障。

### 2. 前端性能优化
词云图放弃 ECharts WordCloud 的 CDN 方案，改用纯 CSS + JavaScript 实现，每个词随机生成大小和颜色，自动换行排列，加载从数秒降为毫秒级，且无需加载外部插件。同时采用正则提取加关键词匹配降级的双重保障，确保数据解析零报错。

### 3. AI Agent 深度融合
基于硅基流动 DeepSeek API 构建智能代理层，用户通过自然语言提问，系统自动完成意图识别、参数提取、SQL构建和数据渲染的全链路闭环。针对大模型输出格式不稳定的工程痛点，设计正则解析层从 markdown 包裹中精准提取 JSON，并在 API 不可用时自动降级到关键词匹配的备用方案。


## 未来改进方向

- 预测模型引入档期竞争力、主创影响力、宣发投入强度等特征因子
- 开发定时爬虫与增量同步任务，实现数据采集自动化
- 将类型等标签字段重构为JSON数组存储，优化查询性能
- 引入更多可视化图表：票房vs预算散点图、类型占比饼图等
- 数据导出功能：支持将筛选结果导出为 CSV/Excel


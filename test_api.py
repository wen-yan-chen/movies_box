import requests
import json
import re

url = "https://api.siliconflow.cn/v1/chat/completions"
api_key = "sk-gqlddjvusikanwvvszouerpojzhpqhouwzodwjzmwdigvqil"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}


def clean_json_response(text):
    """清理 AI 返回的 markdown 代码块，提取纯 JSON"""
    text = text.strip()

    # 方法1: 去掉 ```json ... ```
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    # 方法2: 如果还有问题，尝试用正则提取 JSON
    # 匹配 { ... } 或 [ ... ]
    json_match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', text)
    if json_match:
        text = json_match.group()

    return text


# 测试2: 预测票房
payload2 = {
    "model": "deepseek-ai/DeepSeek-V3",
    "messages": [
        {"role": "system",
         "content": "你是一个电影票房预测助手。用户会描述需求，请提取信息并以JSON格式返回，只返回JSON不要其他内容。格式：{\"intent\": \"predict\", \"predict_year\": 年份, \"predict_genre\": \"类型\", \"predict_budget\": 预算}"},
        {"role": "user", "content": "预测2027年科幻电影的票房，预算5000万"}
    ],
    "temperature": 0.3,
    "max_tokens": 200
}

print("=" * 60)
print("测试: 预测票房")
try:
    response = requests.post(url, json=payload2, headers=headers, timeout=30)
    print(f"状态码: {response.status_code}")
    result = response.json()
    raw_content = result['choices'][0]['message']['content']
    print(f"原始返回:\n{raw_content}")

    # 清理
    cleaned = clean_json_response(raw_content)
    print(f"\n清理后:\n{cleaned}")

    # 解析
    try:
        parsed = json.loads(cleaned)
        print(f"\n解析成功: {json.dumps(parsed, ensure_ascii=False, indent=2)}")
    except json.JSONDecodeError as e:
        print(f"\nJSON解析失败: {e}")
        print(f"问题内容: {cleaned}")

except Exception as e:
    print(f"错误: {e}")
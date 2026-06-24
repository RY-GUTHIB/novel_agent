import os, time, json
from openai import OpenAI

API_KEY = os.getenv("VOLCENGINE_API_KEY", "")
BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
MODELS = ["deepseek-v4-flash", "doubao-1.5-pro-32k"]

def test_model(model: str) -> dict:
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "你好，请回复'ok'"}],
            max_tokens=50,
            timeout=120,
        )
        cost = time.time() - t0
        return {"model": model, "ok": True, "cost": f"{cost:.1f}s",
                "reply": resp.choices[0].message.content}
    except Exception as e:
        cost = time.time() - t0
        return {"model": model, "ok": False, "cost": f"{cost:.1f}s",
                "error": str(e)[:200]}

if __name__ == "__main__":
    print(f"API_KEY: {API_KEY[:10]}..." if API_KEY else "未设置 API_KEY")
    for m in MODELS:
        print(f"\n--- 测试 {m} ---")
        r = test_model(m)
        print(json.dumps(r, ensure_ascii=False, indent=2))

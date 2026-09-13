import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import json

st.set_page_config(page_title="家族の食事・栄養管理アプリ", page_icon="🍽️", layout="centered")

# Streamlit CloudのSecretsからAPIキーを安全に取得
@st.cache_resource
def get_client():
    api_key = st.secrets["GEMINI_API_KEY_EAT"]
    return genai.Client(api_key=api_key)

client = get_client()

# セッションステートでデータを保持（簡易データベース代わり）
if "meal_data" not in st.session_state:
    st.session_state.meal_data = [
        {"date": "2026-09-07", "user": "自分", "meal_time": "朝食", "menu_name": "カルビー フルグラ + 牛乳", "calories": 279.0, "salt": 0.26},
        {"date": "2026-09-07", "user": "お母さん", "meal_time": "朝食", "menu_name": "トースト + 卵", "calories": 250.0, "salt": 0.80},
    ]

st.title("🍽️ 家族の食事・栄養管理アプリ")

# タブ切り替え
tab_self, tab_mom = st.tabs(["👤 自分", "👩 お母さん"])

def user_page(user_name, persona_desc):
    st.header(f"{user_name} のページ")
    st.write(f"**ペルソナ:** {persona_desc}")
    
    # 入力フォーム
    with st.form(key=f"form_{user_name}"):
        input_text = st.text_input("食べたものをざっくり入力（例: 昼にラーメン食べた）", key=f"inp_{user_name}")
        submit = st.form_submit_button("AIで栄養計算して追加")
        
        if submit and input_text:
            with st.spinner("AIが栄養素を解析中..."):
                try:
                    class MealNutrient(BaseModel):
                        menu_name: str = Field(description="料理名または商品名")
                        grams: int = Field(description="グラム数")
                        calories: float = Field(description="カロリー")
                        salt: float = Field(description="塩分")

                    class MealAnalysis(BaseModel):
                        meal_time: str = Field(description="食事時間帯")
                        items: list[MealNutrient]
                        total_calories: float
                        total_salt: float

                    response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=f"以下の食事記録から栄養素を算出して構造化してください：\n{input_text}",
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=MealAnalysis,
                            tools=[{"google_search": {}}],
                            temperature=0.1,
                        )
                    )
                    res_json = json.loads(response.text)
                    
                    st.session_state.meal_data.append({
                        "date": "2026-09-13",
                        "user": user_name,
                        "meal_time": res_json.get("meal_time", "食事"),
                        "menu_name": ", ".join([item["menu_name"] for item in res_json["items"]]),
                        "calories": res_json["total_calories"],
                        "salt": res_json["total_salt"]
                    })
                    st.success("追加しました！")
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

    # データ一覧の表示
    df = pd.DataFrame(st.session_state.meal_data)
    user_df = df[df["user"] == user_name]
    
    st.subheader("📋 記録一覧")
    if not user_df.empty:
        st.dataframe(user_df[["date", "meal_time", "menu_name", "calories", "salt"]])
    else:
        st.info("まだ記録がありません。")

    # 週刊アドバイスボタン
    if st.button(f"💡 {user_name} の週間AIアドバイスをもらう", key=f"adv_{user_name}"):
        with st.spinner("管理栄養士AIが分析中..."):
            avg_cal = user_df["calories"].mean() if not user_df.empty else 0
            avg_salt = user_df["salt"].mean() if not user_df.empty else 0
            
            prompt = f"""
            あなたはプロの管理栄養士です。以下の食事データの平均値とペルソナ情報をもとにアドバイスを作成してください。
            【ユーザー】{user_name}
            【ペルソナ】{persona_desc}
            【直近の平均】カロリー: {avg_cal:.1f} kcal, 塩分: {avg_salt:.1f} g
            構成：1. 今週の総評 2. 具体的な改善提案
            """
            adv_res = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt
            )
            st.markdown(adv_res.text)

with tab_self:
    user_page("自分", "30代会社員、運動習慣あり。筋肉をつけつつバランスを整えたい。")

with tab_mom:
    user_page("お母さん", "60代、血圧と塩分摂取量が少し気になるお年頃。減塩しつつバランス良く。")
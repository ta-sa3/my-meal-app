import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import json
import gspread
from datetime import datetime

st.set_page_config(page_title="家族の食事・栄養管理アプリ", page_icon="🍽️", layout="centered")

# Streamlit CloudのSecretsからAPIキーとスプレッドシート接続情報を取得
@st.cache_resource
def get_clients():
    api_key = st.secrets["GEMINI_API_KEY_EAT"]
    client = genai.Client(api_key=api_key)
    
    # gspreadでスプレッドシートに接続
    gc = gspread.service_account_from_dict(dict(st.secrets["gspread_credentials"]))
    # ※スプレッドシートのファイル名（必要に応じて変更してください）
    sheet = gc.open("my_meal_app_db").sheet1  
    return client, sheet

client, sheet = get_clients()

# スプレッドシートから全データを読み込む関数
def load_data_from_sheet():
    data = sheet.get_all_records()
    if not data:
        return pd.DataFrame(columns=["date", "user", "meal_time", "menu_name", "calories", "salt"])
    return pd.DataFrame(data)

st.title("🍽️ 家族の食事・栄養管理アプリ")

# タブ切り替え
tab_self, tab_mom = st.tabs(["👤 自分", "👩 お母さん"])

# 30分刻みの時間リストを生成 (00:00 〜 23:30)
time_options = []
for hour in range(24):
    for minute in [0, 30]:
        time_options.append(f"{hour:02d}:{minute:02d}")

def user_page(user_name, persona_desc):
    st.header(f"{user_name} のページ")
    st.info(f"**【ペルソナ】** {persona_desc}")
    
    # 入力フォーム
    with st.form(key=f"form_{user_name}"):
        # 時間を選択する欄（30分刻み）
        selected_time = st.selectbox("食事の時間を選択", options=time_options, key=f"time_{user_name}")
        
        # 食べたものを入力する欄
        input_text = st.text_input("食べたものをざっくり入力（例: 納豆ご飯と味噌汁）", key=f"inp_{user_name}")
        
        submit = st.form_submit_button("AIで栄養計算して追加")
        
        if submit and input_text:
            with st.spinner("AIが栄養素を解析中 & スプレッドシートに保存中..."):
                try:
                    class MealNutrient(BaseModel):
                        menu_name: str = Field(description="料理名または商品名")
                        grams: int = Field(description="グラム数")
                        calories: float = Field(description="カロリー")
                        salt: float = Field(description="塩分")

                    class MealAnalysis(BaseModel):
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
                    
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    meal_time_str = selected_time  # 選択した時間をそのまま使用
                    menu_name = ", ".join([item["menu_name"] for item in res_json["items"]])
                    calories = res_json["total_calories"]
                    salt = res_json["total_salt"]
                    
                    # スプレッドシートの末尾に1行追加
                    sheet.append_row([today_str, user_name, meal_time_str, menu_name, calories, salt])
                    
                    st.success("追加してスプレッドシートに保存しました！")
                    st.rerun()
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

    # スプレッドシートからデータを取得して表示
    df = load_data_from_sheet()
    
    st.subheader("📋 記録一覧")
    if not df.empty and "user" in df.columns:
        user_df = df[df["user"] == user_name]
        if not user_df.empty:
            # 時間順にソートして綺麗に見せる
            user_df = user_df.sort_values(by=["date", "meal_time"])
            st.dataframe(user_df[["date", "meal_time", "menu_name", "calories", "salt"]])
        else:
            st.info("まだ記録がありません。")
    else:
        st.info("まだ記録がありません。")

    # 週刊アドバイスボタン
    if st.button(f"💡 {user_name} の週間AIアドバイスをもらう", key=f"adv_{user_name}"):
        with st.spinner("管理栄養士AIが分析中..."):
            df = load_data_from_sheet()
            user_df = df[df["user"] == user_name] if not df.empty and "user" in df.columns else pd.DataFrame()
            avg_cal = user_df["calories"].mean() if not user_df.empty and "calories" in user_df.columns else 0
            avg_salt = user_df["salt"].mean() if not user_df.empty and "salt" in user_df.columns else 0
            
            prompt = f"""
            あなたはプロの管理栄養士です。以下の食事データの平均値とペルソナ情報をもとに、専門的で具体的なアドバイスを作成してください。
            【ユーザー】{user_name}
            【ペルソナ】{persona_desc}
            【直近の平均】カロリー: {avg_cal:.1f} kcal, 塩分: {avg_salt:.1f} g
            構成：1. 今週の総評 2. カロリーと塩分についての詳しい改善提案
            """
            adv_res = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt
            )
            st.markdown(adv_res.text)

with tab_self:
    user_page("自分", "30代、運動習慣なし。筋肉をつけつつカロリーと塩分のバランスを整えたい。")

with tab_mom:
    user_page("お母さん", "60代、高血圧、運動習慣なし。特にカロリー、塩分について詳しいアドバイスが欲しい。")

import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import json
import gspread
from datetime import datetime, timedelta

st.set_page_config(page_title="家族の食事・栄養管理アプリ", page_icon="🍽️", layout="centered")

# Streamlit CloudのSecretsからAPIキーとスプレッドシート接続情報を取得
@st.cache_resource
def get_clients():
    api_key = st.secrets["GEMINI_API_KEY_EAT"]
    client = genai.Client(api_key=api_key)
    
    # gspreadでスプレッドシートに接続
    gc = gspread.service_account_from_dict(dict(st.secrets["gspread_credentials"]))
    sheet = gc.open("my_meal_app_db").sheet1  
    return client, sheet

client, sheet = get_clients()

# 数値の安全な変換用関数
def safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

# スプレッドシートから全データを読み込む関数（row_idx を保持）
def load_data_from_sheet():
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        return pd.DataFrame(columns=["row_idx", "date", "user", "meal_time", "menu_name", "calories", "salt"])
    
    data = []
    for idx, r in enumerate(rows[1:], start=2):
        row_dict = {
            "row_idx": idx,
            "date": r[0] if len(r) > 0 else "",
            "user": r[1] if len(r) > 1 else "",
            "meal_time": r[2] if len(r) > 2 else "",
            "menu_name": r[3] if len(r) > 3 else "",
            "calories": safe_float(r[4]) if len(r) > 4 else 0.0,
            "salt": safe_float(r[5]) if len(r) > 5 else 0.0,
        }
        data.append(row_dict)
    return pd.DataFrame(data)

st.title("🍽️ 家族の食事・栄養管理アプリ")

# タブ切り替え
tab_self, tab_mom = st.tabs(["👤 自分", "👩 お母さん"])

# 30分刻みの時間リストを生成 (00:00 〜 23:30)
time_options = []
for hour in range(24):
    for minute in [0, 30]:
        time_options.append(f"{hour:02d}:{minute:02d}")

# 前後3日間の日付リストを生成（3日前 〜 今日 〜 3日後）
today = datetime.now().date()
date_options = []
for i in range(-3, 4):
    d = today + timedelta(days=i)
    date_options.append(d.strftime("%Y-%m-%d"))

def user_page(user_name, persona_desc):
    st.header(f"{user_name} のページ")
    st.info(f"**【ペルソナ・目標】**\n\n{persona_desc}")
    
    # 入力テキストの状態管理用キー
    input_key = f"input_text_{user_name}"
    if input_key not in st.session_state:
        st.session_state[input_key] = ""

    # ---------------- 1. 新規入力エリア（フォームレス） ----------------
    st.subheader("➕ 新しい食事を記録")
    col1, col2 = st.columns(2)
    with col1:
        selected_date = st.selectbox("日付を選択", options=date_options, index=3, key=f"date_{user_name}")
    with col2:
        selected_time = st.selectbox("時間を選択", options=time_options, key=f"time_{user_name}")
    
    # テキスト入力（session_stateと連動）
    input_text = st.text_input("食べたものをざっくり入力（例: 納豆ご飯と味噌汁）", key=input_key)
    submit = st.button("AIで栄養計算して追加", key=f"btn_add_{user_name}")
    
    if submit:
        if not input_text or input_text.strip() == "":
            st.warning("食べたものを入力してください。")
        else:
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
                    
                    date_str = selected_date
                    meal_time_str = selected_time
                    menu_name = ", ".join([item["menu_name"] for item in res_json["items"]])
                    calories = res_json["total_calories"]
                    salt = res_json["total_salt"]
                    
                    # スプレッドシートの末尾に1行追加
                    sheet.append_row([date_str, user_name, meal_time_str, menu_name, calories, salt])
                    
                    # 入力欄の文字を空にする
                    st.session_state[input_key] = ""
                    st.success("追加してスプレッドシートに保存しました！")
                    st.rerun()
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

    # ---------------- 2. 記録一覧の表示 ----------------
    df = load_data_from_sheet()
    
    st.subheader("📋 記録一覧")
    user_df = pd.DataFrame()
    if not df.empty and "user" in df.columns:
        user_df = df[df["user"] == user_name]
        if not user_df.empty:
            user_df = user_df.sort_values(by=["date", "meal_time"], ascending=[False, False])
            st.dataframe(user_df[["date", "meal_time", "menu_name", "calories", "salt"]], use_container_width=True)
        else:
            st.info("まだ記録がありません。")
    else:
        st.info("まだ記録がありません。")

    # ---------------- 3. 編集・削除メニュー ----------------
    if not user_df.empty:
        with st.expander("✏️ 過去の記録を修正・削除する"):
            options_dict = {
                int(row["row_idx"]): f"【{row['date']} {row['meal_time']}】 {row['menu_name']} ({row['calories']}kcal / 塩分{row['salt']}g)"
                for _, row in user_df.iterrows()
            }
            
            target_row_idx = st.selectbox(
                "修正または削除したい記録を選択してください",
                options=list(options_dict.keys()),
                format_func=lambda x: options_dict[x],
                key=f"sel_edit_{user_name}"
            )
            
            selected_row = user_df[user_df["row_idx"] == target_row_idx].iloc[0]
            
            with st.form(key=f"form_edit_{user_name}_{target_row_idx}"):
                st.write("▼ 修正したい項目を書き換えてください")
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    edit_date = st.text_input("日付 (YYYY-MM-DD)", value=str(selected_row["date"]))
                with col_e2:
                    current_time = str(selected_row["meal_time"])
                    time_idx = time_options.index(current_time) if current_time in time_options else 0
                    edit_time = st.selectbox("時間", options=time_options, index=time_idx)
                
                edit_menu = st.text_input("食べたもの", value=str(selected_row["menu_name"]))
                
                col_e3, col_e4 = st.columns(2)
                with col_e3:
                    edit_cal = st.number_input("カロリー (kcal)", value=float(selected_row["calories"]), step=10.0)
                with col_e4:
                    edit_salt = st.number_input("塩分 (g)", value=float(selected_row["salt"]), step=0.1)
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    update_btn = st.form_submit_button("💾 変更を保存する")
                with col_btn2:
                    delete_btn = st.form_submit_button("🗑️ この記録を削除する")
                
                if update_btn:
                    try:
                        sheet.update(
                            range_name=f"A{target_row_idx}:F{target_row_idx}",
                            values=[[edit_date, user_name, edit_time, edit_menu, edit_cal, edit_salt]]
                        )
                        st.success("記録を更新しました！")
                        st.rerun()
                    except Exception as e:
                        st.error(f"更新に失敗しました: {e}")
                        
                if delete_btn:
                    try:
                        sheet.delete_rows(int(target_row_idx))
                        st.success("記録を削除しました！")
                        st.rerun()
                    except Exception as e:
                        st.error(f"削除に失敗しました: {e}")

    # ---------------- 4. 週間アドバイス ----------------
    if st.button(f"💡 {user_name} の週間AIアドバイスをもらう", key=f"adv_{user_name}"):
        with st.spinner("管理栄養士AIが分析中..."):
            df = load_data_from_sheet()
            user_df = df[df["user"] == user_name] if not df.empty and "user" in df.columns else pd.DataFrame()
            avg_cal = user_df["calories"].mean() if not user_df.empty and "calories" in user_df.columns else 0
            avg_salt = user_df["salt"].mean() if not user_df.empty and "salt" in user_df.columns else 0
            
            prompt = f"""
            あなたは優秀なプロの管理栄養士です。以下の食事データの平均値とユーザーの具体的な身体データ・目標をもとに、専門的で実行しやすい具体的なアドバイスを作成してください。
            【ユーザー】{user_name}
            【ペルソナ・目標】{persona_desc}
            【直近の平均実績】1日あたり平均 カロリー: {avg_cal:.1f} kcal, 塩分: {avg_salt:.1f} g
            
            構成：
            1. 今週の食事の総評（目標達成に向けた進捗評価）
            2. カロリーと塩分についての詳しい改善・調整提案（具体的な食材やメニューの工夫を含む）
            """
            adv_res = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt
            )
            st.markdown(adv_res.text)

with tab_self:
    user_page("自分", "30代男性、身長164cm・体重48kg、運動習慣なし。目標：健康的に筋肉を増やしてバルクアップしたい。")

with tab_mom:
    user_page("お母さん", "60代女性、身長138cm・体重51kg、高血圧、運動習慣なし。目標：血圧管理のために塩分をしっかり抑えつつ、4ヶ月で-3kgを達成する。")

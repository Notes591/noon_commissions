# streamlit_app.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import base64
import requests
from io import BytesIO
import os
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
from PIL import Image

st.set_page_config(page_title="Noon Commissions — AgGrid + GitHub", layout="wide")

# -----------------------------
# GitHub settings (Streamlit secrets)
# -----------------------------
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    GITHUB_USERNAME = st.secrets["GITHUB_USERNAME"]
    GITHUB_REPO = st.secrets["GITHUB_REPO"]
    GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
    API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents"
except Exception:
    st.error("⚠️ أضف Secrets في Streamlit: GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_REPO, (اختياري) GITHUB_BRANCH")
    st.stop()

# -----------------------------
# GitHub helpers
# -----------------------------
def github_upload_bytes(path_in_repo: str, content_bytes: bytes, commit_msg: str):
    url = f"{API_BASE}/{path_in_repo}"
    encoded = base64.b64encode(content_bytes).decode()
    payload = {"message": commit_msg, "content": encoded, "branch": GITHUB_BRANCH}
    res = requests.put(url, json=payload, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    return res

def github_list_dir(path_in_repo: str):
    url = f"{API_BASE}/{path_in_repo}"
    res = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if res.status_code == 200:
        return [item["name"] for item in res.json()]
    return []

def github_get_file(path_in_repo: str):
    url = f"{API_BASE}/{path_in_repo}"
    res = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if res.status_code == 200:
        return res.json()
    return None

def github_delete_file(path_in_repo: str, commit_msg: str):
    info = github_get_file(path_in_repo)
    if not info:
        return None
    sha = info["sha"]
    url = f"{API_BASE}/{path_in_repo}"
    payload = {"message": commit_msg, "sha": sha, "branch": GITHUB_BRANCH}
    res = requests.delete(url, json=payload, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    return res

# -----------------------------
# Utilities (mirror logic from your script)
# -----------------------------
def find_col_like(cols, target):
    if cols is None: return None
    t = str(target).strip().upper()
    for c in cols:
        if str(c).strip().upper() == t:
            return c
    for c in cols:
        if t in str(c).strip().upper():
            return c
    return None

def sum_numeric(series):
    return pd.to_numeric(series, errors='coerce').fillna(0).sum()

def first_nonempty(series):
    non_na = series.dropna().astype(str).str.strip()
    non_na = non_na[non_na != ""]
    return non_na.iloc[0] if not non_na.empty else ""

def ensure_col(df, col, default=0.0):
    if col not in df.columns:
        df[col] = default

def append_totals(df_table):
    if df_table.empty:
        return df_table
    numeric_cols = df_table.select_dtypes(include=['number']).columns
    totals = df_table[numeric_cols].sum()
    total_row = {col: "" for col in df_table.columns}
    for col in numeric_cols:
        total_row[col] = totals[col]
    total_row[list(df_table.columns)[0]] = "الإجمالي"
    return pd.concat([df_table, pd.DataFrame([total_row])], ignore_index=True)

# -----------------------------
# Sidebar: upload / choose / delete
# -----------------------------
st.sidebar.title("📁 إدارة الملفات (GitHub)")
st.sidebar.markdown("رفع ملف Excel/CSV → يخزن في `data/` داخل الريبو. اختر ملفًا لتحليله.")

uploaded = st.sidebar.file_uploader("ارفع ملف Excel/CSV", type=["xlsx","xls","csv"])
if uploaded:
    if st.sidebar.button("🚀 رفع + Commit إلى GitHub"):
        res = github_upload_bytes(f"data/{uploaded.name}", uploaded.read(), f"Upload {uploaded.name}")
        if res.status_code in (200,201):
            st.sidebar.success("✔️ تم الرفع والحفظ في GitHub")
        else:
            st.sidebar.error(f"فشل الرفع: {res.status_code} - {res.text}")

st.sidebar.markdown("---")
files = github_list_dir("data")
sel_file = st.sidebar.selectbox("اختر ملف من data/", files) if files else None
if sel_file and st.sidebar.button("🗑️ حذف الملف من GitHub"):
    res = github_delete_file(f"data/{sel_file}", f"Delete {sel_file}")
    if res and res.status_code == 200:
        st.sidebar.success("✔️ تم الحذف")
        files = github_list_dir("data")
    else:
        st.sidebar.error("❌ فشل الحذف")

st.sidebar.markdown("---")
st.sidebar.info("تأكد أن التوكن يحتوي صلاحيات repo:contents (write)")

# -----------------------------
# Load selected file from GitHub
# -----------------------------
if not sel_file:
    st.info("اختر ملف من الشريط الجانبي (data/) أو ارفعه الآن.")
    st.stop()

raw = github_get_file(f"data/{sel_file}")
if not raw or "content" not in raw:
    st.error("تعذر جلب الملف من GitHub.")
    st.stop()

file_bytes = base64.b64decode(raw["content"])
try:
    df = pd.read_excel(BytesIO(file_bytes))
except Exception:
    df = pd.read_csv(BytesIO(file_bytes))

# keep original df for reference
orig_df = df.copy()
df.columns = [str(c).strip() for c in df.columns]

# -----------------------------
# Detect columns exactly like your script
# -----------------------------
awb_col = find_col_like(df.columns, "awb_nr") or ( [c for c in df.columns if "AWB" in c.upper() or "TRACK" in c.upper()][0] if any("AWB" in c.upper() or "TRACK" in c.upper() for c in df.columns) else df.columns[0] )
order_col = find_col_like(df.columns, "order_nr") or ( [c for c in df.columns if "ORDER" in c.upper()][0] if any("ORDER" in c.upper() for c in df.columns) else df.columns[0] )
marketplace_col = find_col_like(df.columns, "marketplace")
if marketplace_col is None:
    df["marketplace"] = ""
    marketplace_col = "marketplace"
sku_col = find_col_like(df.columns, "sku") or ( [c for c in df.columns if "SKU" in c.upper() or "ITEM" in c.upper() or "PRODUCT" in c.upper()][0] if any("SKU" in c.upper() or "ITEM" in c.upper() or "PRODUCT" in c.upper() for c in df.columns) else df.columns[-1] )
fulfillment_col = find_col_like(df.columns, "fulfillment_mode") or find_col_like(df.columns, "fulfillment")
if fulfillment_col is None:
    df["fulfillment_mode"] = ""
    fulfillment_col = "fulfillment_mode"
base_price_col = find_col_like(df.columns, "base_price") or find_col_like(df.columns, "item_price") or find_col_like(df.columns, "selling_price")
if base_price_col is None:
    df["base_price"] = 0.0
    base_price_col = "base_price"
fee_referral_col = find_col_like(df.columns, "fee_referral") or find_col_like(df.columns, "referral_fee") or find_col_like(df.columns, "commission")
if fee_referral_col is None:
    df["fee_referral"] = 0.0
    fee_referral_col = "fee_referral"
fee_outbound_fbn_col = find_col_like(df.columns, "fee_outbound_fbn") or find_col_like(df.columns, "fbn_outbound_fee") or find_col_like(df.columns, "fulfillment_outbound_fbn")
if fee_outbound_fbn_col is None:
    df["fee_outbound_fbn"] = 0.0
    fee_outbound_fbn_col = "fee_outbound_fbn"
fee_directship_outbound_col = find_col_like(df.columns, "fee_directship_outbound") or find_col_like(df.columns, "fbb_outbound_fee") or find_col_like(df.columns, "directship_outbound")
if fee_directship_outbound_col is None:
    df["fee_directship_outbound"] = 0.0
    fee_directship_outbound_col = "fee_directship_outbound"

# date & partner
date_col = find_col_like(df.columns, "ordered_date") or find_col_like(df.columns, "order_date") or find_col_like(df.columns, "date")
if date_col:
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date
id_partner_col = find_col_like(df.columns, "id_partner") or find_col_like(df.columns, "partner_id")
if id_partner_col:
    df[id_partner_col] = pd.to_numeric(df[id_partner_col], errors="coerce").astype("Int64")

ensure_col(df, "total_payment", 0.0)

# clean fields
df["clean_type"] = df[fulfillment_col].astype(str).str.strip().str.upper()
df["marketplace_norm"] = df[marketplace_col].astype(str).str.strip().str.lower()

# fix sku-first (AWB)
sku_first_map = {}
for _, row in df.iterrows():
    awb = str(row.get(awb_col, "")).strip()
    sku_val = str(row.get(sku_col, "")).strip()
    if sku_val and sku_val.upper() != "NAN":
        if awb not in sku_first_map and awb != "":
            sku_first_map[awb] = sku_val
df["clean_sku"] = df[awb_col].astype(str).map(sku_first_map).fillna("")
df["clean_sku"] = df["clean_sku"].astype(str).str.strip().str.upper()

identifier_like_cols = set([c for c in [awb_col, order_col, sku_col, id_partner_col, date_col] if c])

# -----------------------------
# Build FBB rows (group by AWB + clean_sku)
# -----------------------------
fbb_src = df[df["clean_type"].isin(["FBB", "FBP", "NOON"])].copy()
fbb_rows = []
if not fbb_src.empty:
    for (awb, sku), group in fbb_src.groupby([awb_col, "clean_sku"], dropna=False):
        row = {}
        for col in df.columns:
            if col in identifier_like_cols:
                row[col] = first_nonempty(group[col])
                continue
            nums = pd.to_numeric(group[col], errors="coerce")
            if not nums.isna().all():
                row[col] = float(nums.fillna(0).sum())
            else:
                row[col] = first_nonempty(group[col])
        base_price_sum = sum_numeric(group[base_price_col])
        af_sum = sum_numeric(group[fee_referral_col])
        ak_sum = sum_numeric(group[fee_directship_outbound_col])
        row[base_price_col] = base_price_sum
        row[fee_referral_col] = af_sum
        row[fee_outbound_fbn_col] = 0.0
        row[fee_directship_outbound_col] = ak_sum
        row[awb_col] = awb
        row[sku_col] = sku
        row["نوع"] = "FBB"
        row["نسبة العمولة"] = round(abs(af_sum) / base_price_sum * 100, 2) if base_price_sum else 0.0
        row["سعر بيع تجريبي"] = 0.0
        row["الصافي النهائي"] = round(base_price_sum + af_sum + ak_sum - (base_price_sum * 0.15), 2)
        row["الصافي حسب التجريبي"] = round(0 + af_sum + ak_sum - (0 * 0.15), 2)
        fbb_rows.append(row)
fbb_table = pd.DataFrame(fbb_rows) if fbb_rows else pd.DataFrame(columns=list(df.columns) + ["نوع","نسبة العمولة","سعر بيع تجريبي","الصافي النهائي","الصافي حسب التجريبي"])

# -----------------------------
# Build FBN table (includes Rocket)
# -----------------------------
fbn_src = df[(df["clean_type"] == "FBN") | (df["marketplace_norm"].str.contains("rocket", na=False))].copy()
fbn_table = fbn_src.copy()
if not fbn_table.empty:
    fbn_table["نوع"] = "FBN"
    fbn_table[fee_directship_outbound_col] = 0.0
    base_price_series = pd.to_numeric(fbn_table[base_price_col], errors='coerce').fillna(0)
    af_series = pd.to_numeric(fbn_table[fee_referral_col], errors='coerce').fillna(0)
    ah_series = pd.to_numeric(fbn_table[fee_outbound_fbn_col], errors='coerce').fillna(0)
    fbn_table["نسبة العمولة"] = (af_series.abs() / base_price_series.replace(0, pd.NA) * 100).round(2).fillna(0)
    fbn_table["سعر بيع تجريبي"] = 0.0
    fbn_table["الصافي حسب التجريبي"] = (0 + af_series + ah_series - (0 * 0.15)).round(2)
    fbn_table["الصافي النهائي"] = (base_price_series + af_series + ah_series - (base_price_series * 0.15)).round(2)
else:
    fbn_table = pd.DataFrame(columns=list(df.columns) + ["نوع","نسبة العمولة","سعر بيع تجريبي","الصافي النهائي","الصافي حسب التجريبي"])

# -----------------------------
# Build OTHER (Noon Instant only)
# -----------------------------
other_src = df[df[marketplace_col].astype(str).str.strip().str.lower() == "noon instant"].copy()
other_rows = []
if not other_src.empty:
    for order, group in other_src.groupby(order_col):
        row = {}
        for col in df.columns:
            if col in identifier_like_cols:
                row[col] = first_nonempty(group[col])
                continue
            nums = pd.to_numeric(group[col], errors="coerce")
            if not nums.isna().all():
                row[col] = float(nums.fillna(0).sum())
            else:
                non_na = group[col].dropna().astype(str).str.strip()
                row[col] = ", ".join(pd.unique([v for v in non_na if v != ""])) if not non_na.empty else ""
        base_price_sum = sum_numeric(group[base_price_col])
        af_sum = sum_numeric(group[fee_referral_col])
        ah_sum = sum_numeric(group[fee_outbound_fbn_col])
        ak_sum = sum_numeric(group[fee_directship_outbound_col])
        row[order_col] = order
        row[base_price_col] = base_price_sum
        row[fee_referral_col] = af_sum
        row[fee_outbound_fbn_col] = ah_sum
        row[fee_directship_outbound_col] = ak_sum
        row["نوع"] = "OTHER"
        row["نسبة العمولة"] = round(abs(af_sum) / base_price_sum * 100, 2) if base_price_sum else 0.0
        row["سعر بيع تجريبي"] = 0.0
        row["الصافي حسب التجريبي"] = round(0 + af_sum + ah_sum + ak_sum - (0 * 0.15), 2)
        row["الصافي النهائي"] = round(base_price_sum + af_sum + ah_sum + ak_sum - (base_price_sum * 0.15), 2)
        other_rows.append(row)
other_table = pd.DataFrame(other_rows) if other_rows else pd.DataFrame(columns=list(df.columns) + ["نوع","نسبة العمولة","سعر بيع تجريبي","الصافي النهائي","الصافي حسب التجريبي"])

# -----------------------------
# AgGrid display helper
# -----------------------------
def ordered_columns(df_table):
    cols = list(df_table.columns)
    extras = ["نوع", "نسبة العمولة", "سعر بيع تجريبي", "الصافي النهائي", "الصافي حسب التجريبي"]
    for ex in extras:
        if ex in cols:
            cols.remove(ex)
            cols.append(ex)
    return cols

def aggrid_display(df_table, grid_key):
    if df_table.empty:
        st.info("لا توجد بيانات في هذا الجدول.")
        return df_table
    cols = ordered_columns(df_table)
    # convert numeric columns to numeric dtype for proper grid behavior
    for c in df_table.select_dtypes(include='number').columns:
        df_table[c] = pd.to_numeric(df_table[c], errors='coerce')
    gb = GridOptionsBuilder.from_dataframe(df_table[cols])
    gb.configure_default_column(filter=True, sortable=True, resizable=True, editable=False)
    if "سعر بيع تجريبي" in cols:
        gb.configure_column("سعر بيع تجريبي", editable=True, type=["numericColumn","numberColumnFilter"], precision=2)
    # allow row grouping (user can group using UI)
    gb.configure_grid_options(animateRows=True, enableRangeSelection=True)
    grid_options = gb.build()
    grid_response = AgGrid(
        df_table[cols],
        gridOptions=grid_options,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.MODEL_CHANGED,
        fit_columns_on_grid_load=False,
        theme="alpine",
        enable_enterprise_modules=False,
        allow_unsafe_jscode=False,
        key=grid_key
    )
    updated = pd.DataFrame(grid_response["data"])
    return updated

# -----------------------------
# Main layout: tabs for tables
# -----------------------------
st.title("Noon Commissions — Web (AgGrid) — Images in repo optional")
tabs = st.tabs(["FBB (FBB/FBP/NOON)", "FBN (includes Rocket)", "OTHER (Noon Instant)"])

with tabs[0]:
    st.subheader("طلبات FBB")
    fbb_displayed = aggrid_display(fbb_table, "fbb_grid")
    # recalc trial net on edits
    if not fbb_displayed.empty and "سعر بيع تجريبي" in fbb_displayed.columns:
        for colname in [fee_referral_col, fee_outbound_fbn_col, fee_directship_outbound_col]:
            if colname in fbb_displayed.columns:
                fbb_displayed[colname] = pd.to_numeric(fbb_displayed[colname], errors='coerce').fillna(0)
        fbb_displayed["سعر بيع تجريبي"] = pd.to_numeric(fbb_displayed["سعر بيع تجريبي"], errors='coerce').fillna(0)
        fbb_displayed["الصافي حسب التجريبي"] = (fbb_displayed["سعر بيع تجريبي"] + fbb_displayed.get(fee_referral_col,0) + fbb_displayed.get(fee_outbound_fbn_col,0) + fbb_displayed.get(fee_directship_outbound_col,0) - (fbb_displayed["سعر بيع تجريبي"] * 0.15)).round(2)
    if st.button("💾 تصدير FBB إلى Excel"):
        tmp = BytesIO()
        with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
            fbb_displayed.to_excel(writer, sheet_name="FBB", index=False)
        tmp.seek(0)
        st.download_button("⬇️ تحميل FBB.xlsx", tmp.getvalue(), file_name="FBB.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tabs[1]:
    st.subheader("طلبات FBN")
    fbn_displayed = aggrid_display(fbn_table, "fbn_grid")
    if not fbn_displayed.empty and "سعر بيع تجريبي" in fbn_displayed.columns:
        for colname in [fee_referral_col, fee_outbound_fbn_col]:
            if colname in fbn_displayed.columns:
                fbn_displayed[colname] = pd.to_numeric(fbn_displayed[colname], errors='coerce').fillna(0)
        fbn_displayed["سعر بيع تجريبي"] = pd.to_numeric(fbn_displayed["سعر بيع تجريبي"], errors='coerce').fillna(0)
        fbn_displayed["الصافي حسب التجريبي"] = (fbn_displayed["سعر بيع تجريبي"] + fbn_displayed.get(fee_referral_col,0) + fbn_displayed.get(fee_outbound_fbn_col,0) - (fbn_displayed["سعر بيع تجريبي"] * 0.15)).round(2)
    if st.button("💾 تصدير FBN إلى Excel"):
        tmp = BytesIO()
        with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
            fbn_displayed.to_excel(writer, sheet_name="FBN", index=False)
        tmp.seek(0)
        st.download_button("⬇️ تحميل FBN.xlsx", tmp.getvalue(), file_name="FBN.xlsx", mime="application/vnd.openxmlformats-officedocument-spreadsheetml.sheet")

with tabs[2]:
    st.subheader("طلبات OTHER (Noon Instant)")
    other_displayed = aggrid_display(other_table, "other_grid")
    if not other_displayed.empty and "سعر بيع تجريبي" in other_displayed.columns:
        for colname in [fee_referral_col, fee_outbound_fbn_col, fee_directship_outbound_col]:
            if colname in other_displayed.columns:
                other_displayed[colname] = pd.to_numeric(other_displayed[colname], errors='coerce').fillna(0)
        other_displayed["سعر بيع تجريبي"] = pd.to_numeric(other_displayed["سعر بيع تجريبي"], errors='coerce').fillna(0)
        other_displayed["الصافي حسب التجريبي"] = (other_displayed["سعر بيع تجريبي"] + other_displayed.get(fee_referral_col,0) + other_displayed.get(fee_outbound_fbn_col,0) + other_displayed.get(fee_directship_outbound_col,0) - (other_displayed["سعر بيع تجريبي"] * 0.15)).round(2)
    if st.button("💾 تصدير OTHER إلى Excel"):
        tmp = BytesIO()
        with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
            other_displayed.to_excel(writer, sheet_name="OTHER", index=False)
        tmp.seek(0)
        st.download_button("⬇️ تحميل OTHER.xlsx", tmp.getvalue(), file_name="OTHER.xlsx", mime="application/vnd.openxmlformats-officedocument-spreadsheetml.sheet")

# -----------------------------
# Download combined & save to GitHub
# -----------------------------
st.markdown("---")
st.header("تصدير / حفظ النتائج")

def excel_bytes(tables: dict):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, tbl in tables.items():
            tbl.to_excel(writer, sheet_name=name[:31], index=False)
    out.seek(0)
    return out.getvalue()

fbb_final = fbb_displayed if 'fbb_displayed' in locals() else fbb_table
fbn_final = fbn_displayed if 'fbn_displayed' in locals() else fbn_table
other_final = other_displayed if 'other_displayed' in locals() else other_table

if st.button("⬇️ تنزيل كل الجداول Excel (محلي)"):
    blob = excel_bytes({"FBB": fbb_final, "FBN": fbn_final, "OTHER": other_final})
    st.download_button("📥 تحميل noon_tables.xlsx", data=blob, file_name="noon_tables.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if st.button("💾 حفظ النتائج المعدلة في GitHub (data/modified_<original>)"):
    blob = excel_bytes({"FBB": fbb_final, "FBN": fbn_final, "OTHER": other_final})
    target_name = f"modified_{sel_file}"
    res = github_upload_bytes(f"data/{target_name}", blob, f"Save modified results for {sel_file}")
    if res.status_code in (200,201):
        st.success("✔️ تم حفظ الملف المعدل في GitHub (data/{})".format(target_name))
    else:
        st.error(f"❌ فشل الحفظ: {res.status_code} - {res.text}")

# -----------------------------
# SKU image preview (images/ in repo). Optional: if no image, show info.
# -----------------------------
st.markdown("---")
st.header("عرض صورة SKU (اختياري) — الصور توضع لاحقًا في repo/images/")

sku_input = st.text_input("أدخل SKU لعرض الصورة (بدون الامتداد):").strip().upper()
if sku_input:
    # try png then jpg
    info = github_get_file(f"images/{sku_input}.png") or github_get_file(f"images/{sku_input}.jpg")
    if info and info.get("content"):
        try:
            content = base64.b64decode(info["content"])
            st.image(content, caption=f"SKU: {sku_input}")
        except Exception as e:
            st.error(f"خطأ عند عرض الصورة: {e}")
    else:
        st.info("لا توجد صورة لهذا SKU في مجلد images/ داخل الريبو. يمكنك رفعها لاحقًا (ستظهر تلقائيًا).")

# -----------------------------
# Custom batch calc (AWB/Order)
# -----------------------------
st.markdown("---")
st.header("حساب مخصص لمجموعة AWB / Order")

custom_text = st.text_area("ألصق أرقام AWB أو Order (كل رقم سطر أو مفصول بفاصلة):")
if st.button("📊 احسب للمجموعة"):
    keys = [x.strip() for x in custom_text.replace("\n", ",").split(",") if x.strip()]
    fbb_subset = fbb_final[fbb_final[awb_col].astype(str).isin(keys)] if not fbb_final.empty and awb_col in fbb_final.columns else fbb_final.iloc[0:0]
    fbn_subset = fbn_final[fbn_final[awb_col].astype(str).isin(keys)] if not fbn_final.empty and awb_col in fbn_final.columns else fbn_final.iloc[0:0]
    other_subset = other_final[other_final[order_col].astype(str).isin(keys)] if not other_final.empty and order_col in other_final.columns else other_final.iloc[0:0]
    total_af = 0.0
    total_delivery = 0.0
    total_net = 0.0
    for sub in [fbb_subset, fbn_subset, other_subset]:
        if sub.empty: continue
        total_af += pd.to_numeric(sub.get(fee_referral_col, 0), errors='coerce').fillna(0).sum()
        total_delivery += pd.to_numeric(sub.get(fee_outbound_fbn_col, 0), errors='coerce').fillna(0).sum()
        total_delivery += pd.to_numeric(sub.get(fee_directship_outbound_col, 0), errors='coerce').fillna(0).sum()
        total_net += pd.to_numeric(sub.get("الصافي النهائي", 0), errors='coerce').fillna(0).sum()
    total_orders = 0
    if not fbb_subset.empty and awb_col in fbb_subset.columns:
        total_orders += fbb_subset[awb_col].nunique()
    if not fbn_subset.empty and awb_col in fbn_subset.columns:
        total_orders += fbn_subset[awb_col].nunique()
    if not other_subset.empty and order_col in other_subset.columns:
        total_orders += other_subset[order_col].nunique()
    total_sku_count = 0
    if not fbb_subset.empty and sku_col in fbb_subset.columns:
        total_sku_count += fbb_subset[sku_col].count()
    if not fbn_subset.empty and sku_col in fbn_subset.columns:
        total_sku_count += fbn_subset[sku_col].count()
    st.success(f"📊 إجمالي السجلات: {total_orders} | إجمالي تكرارات SKU: {total_sku_count} | إجمالي العمولة: {round(total_af,2)} | إجمالي التوصيل: {round(total_delivery,2)} | إجمالي الصافي: {round(total_net,2)}")

st.info("ملاحظة: الصور اختيارية — إن لم توجد لن يتوقف التطبيق. أضف الصور لاحقًا إلى images/ داخل الريبو.")


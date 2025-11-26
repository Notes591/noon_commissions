# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import numpy as np
import base64
import requests
from io import BytesIO
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
from PIL import Image
import os

st.set_page_config(
    page_title="Noon Full Commission System",
    layout="wide"
)

# ============================================================
#    GitHub Secrets (Stored in Streamlit Cloud)
# ============================================================
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    GITHUB_USERNAME = st.secrets["GITHUB_USERNAME"]
    GITHUB_REPO = st.secrets["GITHUB_REPO"]
    GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
    API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents"
except Exception:
    st.error("""
🔴 أضف Secrets في Streamlit:

- GITHUB_TOKEN
- GITHUB_USERNAME
- GITHUB_REPO
- (اختياري) GITHUB_BRANCH
""")
    st.stop()


# ============================================================
#    GitHub Helper Functions
# ============================================================
def gh_upload(path, bytes_data, message):
    url = f"{API_BASE}/{path}"
    encoded = base64.b64encode(bytes_data).decode()
    payload = {
        "message": message,
        "content": encoded,
        "branch": GITHUB_BRANCH
    }
    return requests.put(url, json=payload,
                        headers={"Authorization": f"token {GITHUB_TOKEN}"})


def gh_list(path):
    res = requests.get(f"{API_BASE}/{path}",
                       headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if res.status_code == 200:
        return [x["name"] for x in res.json()]
    return []


def gh_get(path):
    res = requests.get(f"{API_BASE}/{path}",
                       headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if res.status_code == 200:
        return res.json()
    return None


def gh_delete(path, msg):
    file_info = gh_get(path)
    if not file_info:
        return None
    payload = {
        "message": msg,
        "sha": file_info["sha"],
        "branch": GITHUB_BRANCH
    }
    return requests.delete(f"{API_BASE}/{path}",
                           json=payload,
                           headers={"Authorization": f"token {GITHUB_TOKEN}"})


# ============================================================
#     SAFE FILE READER  — يحل مشكلة "File is not a zip file"
# ============================================================
def read_file_safely(file_bytes, filename):
    from io import BytesIO
    name = filename.lower()

    # CSV أولًا
    if name.endswith(".csv"):
        return pd.read_csv(BytesIO(file_bytes),
                           encoding="utf-8",
                           errors="ignore")

    # Excel
    if name.endswith(".xlsx") or name.endswith(".xls"):
        try:
            return pd.read_excel(BytesIO(file_bytes), engine="openpyxl")
        except Exception:
            try:
                return pd.read_csv(BytesIO(file_bytes),
                                   encoding="utf-8",
                                   errors="ignore")
            except Exception as e:
                raise Exception(f"🚨 الملف Excel لكن غير صالح — {e}")

    # fallback
    try:
        return pd.read_csv(BytesIO(file_bytes),
                           encoding="utf-8",
                           errors="ignore")
    except:
        raise Exception("⚠️ غير قادر على قراءة الملف")


# ============================================================
# Sidebar — إدارة الملفات
# ============================================================
st.sidebar.header("📦 إدارة ملفات المبيعات")

uploaded = st.sidebar.file_uploader("🟢 ارفع ملف CSV/XLS/XLSX")

if uploaded and st.sidebar.button("⬆️ رفع إلى GitHub"):
    res = gh_upload(
        f"data/{uploaded.name}",
        uploaded.read(),
        f"upload {uploaded.name}"
    )
    st.sidebar.success("✔️ تم رفع الملف") if res.status_code in (200, 201) else st.sidebar.error("❌ فشل الرفع")

files = gh_list("data")
selected_file = st.sidebar.selectbox("📁 اختر ملف", files) if files else None

if selected_file and st.sidebar.button("🗑️ حذف الملف"):
    res = gh_delete(f"data/{selected_file}", f"delete {selected_file}")
    st.sidebar.success("✔️ تم الحذف") if res and res.status_code == 200 else st.sidebar.error("❌ فشل الحذف")


# ============================================================
# Load + Parse
# ============================================================
if not selected_file:
    st.info("اختر ملف من الشريط الجانبي")
    st.stop()

raw_data = gh_get(f"data/{selected_file}")
file_bytes = base64.b64decode(raw_data["content"])

try:
    df = read_file_safely(file_bytes, selected_file)
except Exception as e:
    st.error(f"⚠️ خطأ أثناء قراءة الملف:\n{e}")
    st.stop()

df.columns = [c.strip() for c in df.columns]
orig_df = df.copy()


# ============================================================
#     CORE — عمود SKU + Fulfillment + السعر + البيع
# ============================================================
def find_col(cols, key):
    key = key.strip().upper()
    for c in cols:
        if str(c).strip().upper() == key:
            return c
    for c in cols:
        if key in str(c).upper():
            return c
    return None


SKU = find_col(df.columns, "sku")
F_MODE = find_col(df.columns, "fulfillment_mode")
SALE = find_col(df.columns, "sale_price")
QTY = find_col(df.columns, "quantity")


for c, d in [
    (SALE, 0),
    (QTY, 0)
]:
    if c and c not in df.columns:
        df[c] = d

df["sales_value"] = pd.to_numeric(df.get(SALE, 0), errors="coerce") \
                     * pd.to_numeric(df.get(QTY, 0), errors="coerce")


# ============================================================
# UI — AgGrid
# ============================================================
st.subheader("📊 جدول Raw Data")
gb = GridOptionsBuilder.from_dataframe(df)
gb.configure_pagination()
gb.configure_default_column(editable=True, filter=True, sortable=True, groupable=True)
grid = AgGrid(
    df,
    gridOptions=gb.build(),
    height=450,
    update_mode=GridUpdateMode.MODEL_CHANGED
)
df = grid["data"]
# ------------------ الجزء الثاني: تجميع الجداول، الحسابات، الـ AgGrid لكل جدول، التصدير، الصور، الحفظ ------------------

# -----------------------------
# Utility helpers (إذا لم تُعرّف من قبل)
# -----------------------------
def sum_numeric(series):
    return pd.to_numeric(series, errors='coerce').fillna(0).sum()

def first_nonempty(series):
    non_na = series.dropna().astype(str).str.strip()
    non_na = non_na[non_na != ""]
    return non_na.iloc[0] if not non_na.empty else ""

def ensure_col(df_local, col, default=0.0):
    if col not in df_local.columns:
        df_local[col] = default

# -----------------------------
# اكتشاف أعمدة مهمة (مطابق للنسخة الكبيرة)
# -----------------------------
awb_col = find_col(df.columns, "awb_nr") or ([c for c in df.columns if "AWB" in c.upper() or "TRACK" in c.upper()][0] if any("AWB" in c.upper() or "TRACK" in c.upper() for c in df.columns) else df.columns[0])
order_col = find_col(df.columns, "order_nr") or ([c for c in df.columns if "ORDER" in c.upper()][0] if any("ORDER" in c.upper() for c in df.columns) else df.columns[0])
marketplace_col = find_col(df.columns, "marketplace")
if marketplace_col is None:
    df["marketplace"] = ""
    marketplace_col = "marketplace"
sku_col = find_col(df.columns, "sku") or ([c for c in df.columns if "SKU" in c.upper() or "ITEM" in c.upper() or "PRODUCT" in c.upper()][0] if any("SKU" in c.upper() or "ITEM" in c.upper() or "PRODUCT" in c.upper() for c in df.columns) else df.columns[-1])
fulfillment_col = find_col(df.columns, "fulfillment_mode") or find_col(df.columns, "fulfillment")
if fulfillment_col is None:
    df["fulfillment_mode"] = ""
    fulfillment_col = "fulfillment_mode"
base_price_col = find_col(df.columns, "base_price") or find_col(df.columns, "item_price") or find_col(df.columns, "selling_price") or find_col(df.columns, "price") or None
if base_price_col is None:
    df["base_price"] = 0.0
    base_price_col = "base_price"
fee_referral_col = find_col(df.columns, "fee_referral") or find_col(df.columns, "referral_fee") or find_col(df.columns, "commission") or find_col(df.columns, "fee")
if fee_referral_col is None:
    df["fee_referral"] = 0.0
    fee_referral_col = "fee_referral"
fee_outbound_fbn_col = find_col(df.columns, "fee_outbound_fbn") or find_col(df.columns, "fbn_outbound_fee") or find_col(df.columns, "fulfillment_outbound_fbn") or None
if fee_outbound_fbn_col is None:
    df["fee_outbound_fbn"] = 0.0
    fee_outbound_fbn_col = "fee_outbound_fbn"
fee_directship_outbound_col = find_col(df.columns, "fee_directship_outbound") or find_col(df.columns, "fbb_outbound_fee") or find_col(df.columns, "directship_outbound") or None
if fee_directship_outbound_col is None:
    df["fee_directship_outbound"] = 0.0
    fee_directship_outbound_col = "fee_directship_outbound"

# تاريخ و partner
date_col = find_col(df.columns, "ordered_date") or find_col(df.columns, "order_date") or find_col(df.columns, "date")
if date_col:
    try:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    except Exception:
        pass

id_partner_col = find_col(df.columns, "id_partner") or find_col(df.columns, "partner_id")
if id_partner_col:
    try:
        df[id_partner_col] = pd.to_numeric(df[id_partner_col], errors="coerce").astype("Int64")
    except Exception:
        pass

ensure_col(df, "total_payment", 0.0)

# -----------------------------
# تنظيف الحقول الأساسية المستخدمة
# -----------------------------
df["clean_type"] = df[fulfillment_col].astype(str).str.strip().str.upper()
df["marketplace_norm"] = df[marketplace_col].astype(str).str.strip().str.lower()

# map sku-first by AWB (كما في كودك الأصلي)
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
# Build FBB grouped table
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
# Build FBN table
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
# Build OTHER table (Noon Instant)
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
# AgGrid display function for grouped tables
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
# Main UI: tabs for the 3 tables (FBB / FBN / OTHER)
# -----------------------------
st.title("نتائج التحليل — FBB / FBN / OTHER")
tab1, tab2, tab3 = st.tabs(["FBB (FBB/FBP/NOON)", "FBN (يشمل Rocket)", "OTHER (Noon Instant)"])

with tab1:
    st.subheader("طلبات FBB")
    fbb_displayed = aggrid_display(fbb_table, "fbb_grid")
    if not fbb_displayed.empty and "سعر بيع تجريبي" in fbb_displayed.columns:
        # ensure numeric
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

with tab2:
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
        st.download_button("⬇️ تحميل FBN.xlsx", tmp.getvalue(), file_name="FBN.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab3:
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
# Export combined & save to GitHub
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

fbb_final = fbb_displayed if 'fbb_displayed' in locals() and not fbb_displayed.empty else fbb_table
fbn_final = fbn_displayed if 'fbn_displayed' in locals() and not fbn_displayed.empty else fbn_table
other_final = other_displayed if 'other_displayed' in locals() and not other_displayed.empty else other_table

if st.button("⬇️ تنزيل كل الجداول Excel (محلي)"):
    blob = excel_bytes({"FBB": fbb_final, "FBN": fbn_final, "OTHER": other_final})
    st.download_button("📥 تحميل noon_tables.xlsx", data=blob, file_name="noon_tables.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if st.button("💾 حفظ النتائج المعدلة في GitHub (data/modified_<original>)"):
    blob = excel_bytes({"FBB": fbb_final, "FBN": fbn_final, "OTHER": other_final})
    target_name = f"modified_{selected_file}"
    res = gh_upload(f"data/{target_name}", blob, f"Save modified results for {selected_file}")
    if res.status_code in (200,201):
        st.success(f"✔️ تم حفظ الملف المعدل في GitHub (data/{target_name})")
    else:
        st.error(f"❌ فشل الحفظ: {res.status_code} - {res.text}")

# -----------------------------
# SKU image preview (images/ in repo). Optional: if no image, show info.
# -----------------------------
st.markdown("---")
st.header("عرض صورة SKU (اختياري) — ضع الصور لاحقًا في images/ داخل الريبو")

sku_input = st.text_input("أدخل SKU لعرض الصورة (بدون الامتداد):").strip().upper()
if sku_input:
    info = gh_get(f"images/{sku_input}.png") or gh_get(f"images/{sku_input}.jpg")
    if info and info.get("content"):
        try:
            content = base64.b64decode(info["content"])
            st.image(content, caption=f"SKU: {sku_input}")
        except Exception as e:
            st.error(f"خطأ عند عرض الصورة: {e}")
    else:
        st.info("لا توجد صورة لهذا SKU في مجلد images/ داخل الريبو. يمكنك رفعها لاحقًا.")

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

st.info("ملاحظة: الصور اختيارية — إن لم تُضاف لن يتوقف التطبيق. أضفها لاحقًا في images/ داخل الريبو.")

# streamlit_app.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import io
import base64
import requests
import os
from io import BytesIO
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
from st_aggrid.shared import GridUpdateType

st.set_page_config(page_title="Noon Commissions — AgGrid + GitHub", layout="wide")

# ---------------------------
# GitHub settings (from secrets)
# ---------------------------
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    GITHUB_USERNAME = st.secrets["GITHUB_USERNAME"]
    GITHUB_REPO = st.secrets["GITHUB_REPO"]
    GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
    API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents"
except Exception as e:
    st.error("⚠️ لم يتم إعداد GitHub secrets. أضف GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_REPO في إعدادات Streamlit Secrets.")
    st.stop()

# ---------------------------
# Helper functions (same logic as كودك)
# ---------------------------
def find_col_like(df_cols, target):
    target_up = str(target).strip().upper()
    # exact
    for c in df_cols:
        if str(c).strip().upper() == target_up:
            return c
    for c in df_cols:
        if target_up in str(c).strip().upper():
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

# ---------------------------
# GitHub API helpers
# ---------------------------
def github_upload_bytes(path_in_repo, content_bytes, commit_message):
    """Upload or update file to GitHub (path_in_repo without leading slash)."""
    url = f"{API_BASE}/{path_in_repo}"
    encoded = base64.b64encode(content_bytes).decode()
    payload = {
        "message": commit_message,
        "content": encoded,
        "branch": GITHUB_BRANCH
    }
    res = requests.put(url, json=payload, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    return res

def github_list_dir(path_in_repo):
    url = f"{API_BASE}/{path_in_repo}"
    res = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if res.status_code == 200:
        return [item["name"] for item in res.json()]
    return []

def github_get_file(path_in_repo):
    url = f"{API_BASE}/{path_in_repo}"
    res = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if res.status_code == 200:
        return res.json()
    return None

def github_delete_file(path_in_repo, commit_message):
    info = github_get_file(path_in_repo)
    if not info:
        return None
    sha = info["sha"]
    url = f"{API_BASE}/{path_in_repo}"
    payload = {"message": commit_message, "sha": sha, "branch": GITHUB_BRANCH}
    res = requests.delete(url, json=payload, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    return res

# ---------------------------
# UI: Left sidebar - file operations
# ---------------------------
st.sidebar.title("📁 GitHub File Storage")
st.sidebar.markdown("رفع ملفات Excel/CSV إلى المجلد `data/` في الريبو، حذف الملفات، واختيار ملف للتحليل.")

# Upload to GitHub
uploaded = st.sidebar.file_uploader("ارفع ملف Excel (xlsx/xls) أو CSV", type=["xlsx","xls","csv"])
if uploaded:
    name = uploaded.name
    st.sidebar.write(f"ملف مُحدد: **{name}**")
    if st.sidebar.button("🚀 رفع + Commit إلى GitHub"):
        # ensure data/ folder exists (GitHub API will create path automatically)
        content = uploaded.read()
        res = github_upload_bytes(f"data/{name}", content, f"Upload {name}")
        if res.status_code in (200,201):
            st.sidebar.success("✔️ تم رفع الملف وحفظه في GitHub")
        else:
            st.sidebar.error(f"❌ فشل الرفع: {res.status_code} - {res.text}")

# List files on GitHub / choose file to analyze
st.sidebar.markdown("---")
files = github_list_dir("data")
if files:
    sel_file = st.sidebar.selectbox("اختر ملف من GitHub للتحليل", files)
    if st.sidebar.button("🗑️ حذف الملف المحدد من GitHub"):
        res = github_delete_file(f"data/{sel_file}", f"Delete {sel_file}")
        if res and res.status_code == 200:
            st.sidebar.success("✔️ تم الحذف")
            files = github_list_dir("data")
        else:
            st.sidebar.error(f"❌ فشل الحذف: {res.status_code if res else 'no_response'}")
else:
    sel_file = None
    st.sidebar.info("لا توجد ملفات في المجلد data/")

st.sidebar.markdown("---")
st.sidebar.info("Secrets: GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_REPO, GITHUB_BRANCH")

# ---------------------------
# Main UI
# ---------------------------
st.title("Noon Commissions — AgGrid edition")
st.markdown("عرض وتحليل ملفات Noon كما في نسخة سطح المكتب — مع حفظ الملفات في GitHub.")

# Load DataFrame from selected GitHub file
df = None
original_filename = None
if sel_file:
    raw = github_get_file(f"data/{sel_file}")
    if raw:
        original_filename = sel_file
        content_b64 = raw.get("content", "")
        try:
            file_bytes = base64.b64decode(content_b64)
            # try excel then csv
            try:
                df = pd.read_excel(BytesIO(file_bytes))
            except Exception:
                df = pd.read_csv(BytesIO(file_bytes))
            st.success(f"✔️ تم تحميل الملف: {sel_file}")
        except Exception as e:
            st.error(f"تعذر فك محتوى الملف: {e}")
else:
    st.info("اختر ملف من الشريط الجانبي أو ارفع ملف جديد.")

if df is None:
    st.stop()

# ---------------------------
# Apply original logic (mirror exactly)
# ---------------------------
# normalize column names
df.columns = [str(c).strip() for c in df.columns]

# detect columns using same heuristics
awb_col = find_col_like(df.columns, "awb_nr")
if awb_col is None:
    candidates = [c for c in df.columns if "AWB" in c.upper() or "TRACK" in c.upper()]
    awb_col = candidates[0] if candidates else df.columns[0]

order_col = find_col_like(df.columns, "order_nr") or ([c for c in df.columns if "ORDER" in c.upper()][0] if any("ORDER" in c.upper() for c in df.columns) else df.columns[0])
marketplace_col = find_col_like(df.columns, "marketplace")
if marketplace_col is None:
    df["marketplace"] = ""
    marketplace_col = "marketplace"

sku_col = find_col_like(df.columns, "sku") or ([c for c in df.columns if "SKU" in c.upper() or "ITEM" in c.upper() or "PRODUCT" in c.upper()][0] if any("SKU" in c.upper() or "ITEM" in c.upper() or "PRODUCT" in c.upper() for c in df.columns) else df.columns[-1])

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

df["clean_type"] = df[fulfillment_col].astype(str).str.strip().str.upper()
df["marketplace_norm"] = df[marketplace_col].astype(str).str.strip().str.lower()

# fix sku-first by AWB
sku_first_map = {}
for _, row in df.iterrows():
    awb = str(row.get(awb_col, "")).strip()
    sku_val = str(row.get(sku_col, "")).strip()
    if sku_val and sku_val.upper() != "NAN":
        if awb not in sku_first_map and awb != "":
            sku_first_map[awb] = sku_val
df["clean_sku"] = df[awb_col].astype(str).map(sku_first_map).fillna("")
df["clean_sku"] = df["clean_sku"].astype(str).str.strip().str.upper()

# identifier-like cols
identifier_like_cols = set([c for c in [awb_col, order_col, sku_col, id_partner_col, date_col] if c])

# Build FBB table
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

# Build FBN table (includes rocket)
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

# Build OTHER table (Noon Instant)
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

# ---------------------------
# Functions to show and edit with AgGrid
# ---------------------------
def ordered_columns(df_table):
    cols = list(df_table.columns)
    extras = ["نوع", "نسبة العمولة", "سعر بيع تجريبي", "الصافي النهائي", "الصافي حسب التجريبي"]
    for ex in extras:
        if ex in cols:
            cols.remove(ex)
            cols.append(ex)
    return cols

def aggrid_display(df_table, key):
    """Render AgGrid editable for column 'سعر بيع تجريبي' and support grouping/sorting/filtering."""
    if df_table.empty:
        st.info("لا توجد بيانات في هذا الجدول.")
        return df_table

    cols = ordered_columns(df_table)
    gdf = df_table.copy()
    # Ensure numeric columns are numeric for AgGrid
    for c in gdf.select_dtypes(include='number').columns:
        gdf[c] = pd.to_numeric(gdf[c], errors='coerce')
    gb = GridOptionsBuilder.from_dataframe(gdf[cols])
    gb.configure_default_column(editable=False, filter=True, sortable=True, resizable=True)
    # enable editing only on the 'سعر بيع تجريبي' column
    if "سعر بيع تجريبي" in cols:
        gb.configure_column("سعر بيع تجريبي", editable=True, type=["numericColumn","numberColumnFilter"], precision=2)
    # allow row grouping on AWB / order / SKU
    # choose some common groupable columns if present
    group_cols = []
    for c in [awb_col, order_col, sku_col]:
        if c in cols:
            gb.configure_column(c, rowGroup=True)  # user can enable grouping via UI
            group_cols.append(c)
    gb.configure_grid_options(enableRangeSelection=True, animateRows=True)
    gridOptions = gb.build()

    grid_response = AgGrid(
        gdf[cols],
        gridOptions=gridOptions,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.MODEL_CHANGED,
        fit_columns_on_grid_load=False,
        enable_enterprise_modules=False,
        allow_unsafe_jscode=False,
        theme="alpine"
    )
    updated_df = pd.DataFrame(grid_response["data"])
    return updated_df

# ---------------------------
# Tabs for three tables
# ---------------------------
tab1, tab2, tab3 = st.tabs(["FBB (FBB/FBP/NOON)", "FBN (يشمل Rocket)", "OTHER (Noon Instant)"])

with tab1:
    st.subheader("طلبات FBB")
    fbb_updated = aggrid_display(fbb_table, "fbb_grid")
    # recalc 'الصافي حسب التجريبي' when 'سعر بيع تجريبي' changed
    if not fbb_updated.empty:
        # find numeric fee columns with fallback to 0
        af_col = fee_referral_col if fee_referral_col in fbb_updated.columns else fee_referral_col
        ah_col = fee_outbound_fbn_col if fee_outbound_fbn_col in fbb_updated.columns else fee_outbound_fbn_col
        ak_col = fee_directship_outbound_col if fee_directship_outbound_col in fbb_updated.columns else fee_directship_outbound_col
        # safe to_numeric
        for c in [af_col, ah_col, ak_col, "سعر بيع تجريبي"]:
            if c in fbb_updated.columns:
                fbb_updated[c] = pd.to_numeric(fbb_updated[c], errors='coerce').fillna(0)
        if "سعر بيع تجريبي" in fbb_updated.columns:
            fbb_updated["الصافي حسب التجريبي"] = (fbb_updated["سعر بيع تجريبي"] + fbb_updated.get(af_col,0) + fbb_updated.get(ah_col,0) + fbb_updated.get(ak_col,0) - (fbb_updated["سعر بيع تجريبي"] * 0.15)).round(2)
    st.download_button("💾 تنزيل FBB إلى Excel", data=BytesIO(pd.ExcelWriter if False else b''), file_name="FBB.xlsx")  # placeholder below
    # Export button (real)
    if st.button("💾 تصدير FBB إلى ملف Excel (محلي)"):
        to_write = BytesIO()
        with pd.ExcelWriter(to_write, engine="openpyxl") as writer:
            fbb_updated.to_excel(writer, sheet_name="FBB", index=False)
        to_write.seek(0)
        st.download_button("⬇️ حمل FBB.xlsx", to_write.getvalue(), file_name="FBB.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab2:
    st.subheader("طلبات FBN")
    fbn_updated = aggrid_display(fbn_table, "fbn_grid")
    if not fbn_updated.empty:
        af_col = fee_referral_col
        ah_col = fee_outbound_fbn_col
        for c in [af_col, ah_col, "سعر بيع تجريبي"]:
            if c in fbn_updated.columns:
                fbn_updated[c] = pd.to_numeric(fbn_updated[c], errors='coerce').fillna(0)
        if "سعر بيع تجريبي" in fbn_updated.columns:
            fbn_updated["الصافي حسب التجريبي"] = (fbn_updated["سعر بيع تجريبي"] + fbn_updated.get(af_col,0) + fbn_updated.get(ah_col,0) - (fbn_updated["سعر بيع تجريبي"] * 0.15)).round(2)
    if st.button("💾 تصدير FBN إلى ملف Excel (محلي)"):
        to_write = BytesIO()
        with pd.ExcelWriter(to_write, engine="openpyxl") as writer:
            fbn_updated.to_excel(writer, sheet_name="FBN", index=False)
        to_write.seek(0)
        st.download_button("⬇️ حمل FBN.xlsx", to_write.getvalue(), file_name="FBN.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab3:
    st.subheader("طلبات OTHER (Noon Instant)")
    other_updated = aggrid_display(other_table, "other_grid")
    if not other_updated.empty:
        cols_to_num = [fee_referral_col, fee_outbound_fbn_col, fee_directship_outbound_col, "سعر بيع تجريبي"]
        for c in cols_to_num:
            if c in other_updated.columns:
                other_updated[c] = pd.to_numeric(other_updated[c], errors='coerce').fillna(0)
        if "سعر بيع تجريبي" in other_updated.columns:
            other_updated["الصافي حسب التجريبي"] = (other_updated["سعر بيع تجريبي"] + other_updated.get(fee_referral_col,0) + other_updated.get(fee_outbound_fbn_col,0) + other_updated.get(fee_directship_outbound_col,0) - (other_updated["سعر بيع تجريبي"] * 0.15)).round(2)
    if st.button("💾 تصدير OTHER إلى ملف Excel (محلي)"):
        to_write = BytesIO()
        with pd.ExcelWriter(to_write, engine="openpyxl") as writer:
            other_updated.to_excel(writer, sheet_name="OTHER", index=False)
        to_write.seek(0)
        st.download_button("⬇️ حمل OTHER.xlsx", to_write.getvalue(), file_name="OTHER.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------------------------
# Export combined Excel & optionally save to GitHub
# ---------------------------
st.markdown("---")
st.header("تصدير / حفظ التغييرات")

def excel_bytes_from_tables(tables_dict):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, df_tbl in tables_dict.items():
            df_tbl.to_excel(writer, sheet_name=name[:31], index=False)
    out.seek(0)
    return out.getvalue()

# use updated tables if exist else original
fbb_final = fbb_updated if 'fbb_updated' in locals() and not fbb_updated.empty else fbb_table
fbn_final = fbn_updated if 'fbn_updated' in locals() and not fbn_updated.empty else fbn_table
other_final = other_updated if 'other_updated' in locals() and not other_updated.empty else other_table

if st.button("⬇️ تنزيل كل الجداول Excel محلياً"):
    blob = excel_bytes_from_tables({"FBB": fbb_final, "FBN": fbn_final, "OTHER": other_final})
    st.download_button("📥 تحميل noon_tables.xlsx", data=blob, file_name="noon_tables.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# Save combined to GitHub (optional)
if original_filename:
    if st.button("💾 حفظ ملف النتائج في GitHub (data/modified_<original>)"):
        out_blob = excel_bytes_from_tables({"FBB": fbb_final, "FBN": fbn_final, "OTHER": other_final})
        target_name = f"modified_{original_filename}"
        res = github_upload_bytes(f"data/{target_name}", out_blob, f"Save modified results for {original_filename}")
        if res.status_code in (200,201):
            st.success("✔️ تم حفظ الملف المعدل في GitHub")
        else:
            st.error(f"❌ فشل الحفظ: {res.status_code} - {res.text}")

# ---------------------------
# SKU Image preview (from repo images/)
# ---------------------------
st.markdown("---")
st.header("عرض صورة SKU (اختياري)")

sku_input = st.text_input("أدخل SKU لعرض الصورة (بدون الامتداد):").strip().upper()
if sku_input:
    # try get image from repo images/<sku>.png (via API)
    info = github_get_file(f"images/{sku_input}.png")
    if not info:
        info = github_get_file(f"images/{sku_input}.jpg")
    if info and info.get("content"):
        try:
            content = base64.b64decode(info["content"])
            st.image(content, caption=f"SKU: {sku_input}")
        except Exception as e:
            st.error(f"خطأ عند عرض الصورة: {e}")
    else:
        st.info("لا توجد صورة لهذا SKU في مجلد images/ بالريبو. يمكنك رفعها لاحقاً.")

# ---------------------------
# Custom AWB/Order batch calc (مثل كودك)
# ---------------------------
st.markdown("---")
st.header("حساب مخصص لمجموعة AWB / Order")

custom_text = st.text_area("ألصق أرقام AWB أو Order (كل رقم بسطر أو مفصول بفاصلة):")
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

st.markdown("**ملاحظة:** الصور اختيارية — إذا لم تكن موجودة في مجلد `images/` داخل الريبو، التطبيق لن يتوقف وسيعرض رسالة مناسبة.")


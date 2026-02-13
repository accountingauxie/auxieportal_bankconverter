import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- CONFIG ---
st.set_page_config(page_title="Bank Converter v7", layout="wide")
st.title("💰 Multi-Bank Converter (v7.0 - Final)")

# --- UI ---
col1, col2 = st.columns(2)
with col1:
    bank_type = st.selectbox("1. Pilih Bank", ["BCA / Mandiri", "BRI", "Panin"])
    uploaded_file = st.file_uploader("2. Upload PDF", type="pdf")
with col2:
    pdf_password = st.text_input("3. Password (Jika ada)", type="password", help="Kosongkan jika PDF tidak dikunci")
    tahun_input = st.text_input("4. Tahun (Hanya BCA/Mandiri)", value="2026")

# --- UTILITY: MEMBERSIHKAN ANGKA ---
def clean_money(text, is_intl=False):
    if not text: return "0,00"
    s = str(text).strip().replace('\n', ' ')
    if is_intl: # BRI: 1,000.00 -> 1.000,00
        s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
    return s

# --- PARSER BRI (Improved Table Strategy) ---
def parse_bri(pdf):
    data = []
    for page in pdf.pages:
        table = page.extract_table(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"})
        if not table: continue
        for row in table:
            if len(row) >= 6 and row[0] and re.search(r'\d{2}/\d{2}/\d{2}', str(row[0])):
                deb = str(row[3]).strip() if row[3] else ""
                kre = str(row[4]).strip() if row[4] else ""
                is_db = deb != "" and deb != "0.00" and deb != "0"
                
                data.append({
                    "Tanggal Transaksi": str(row[0]).split(' ')[0].replace('/01/', '/01/20'), # Fix year
                    "Keterangan": str(row[1]).replace('\n', ' '),
                    "Cabang": str(row[2]),
                    "Jumlah": f"{clean_money(deb if is_db else kre, True)} {'DB' if is_db else 'CR'}",
                    "Saldo": clean_money(row[5], True)
                })
    return pd.DataFrame(data)

# --- PARSER PANIN (New Row-by-Row Strategy) ---
def parse_panin(pdf):
    data = []
    current_trx = None
    date_regex = re.compile(r'(\d{1,2}-[a-zA-Z]{3}-\d{4})')
    
    for page in pdf.pages:
        text = page.extract_text()
        if not text: continue
        for line in text.split('\n'):
            match = date_regex.search(line)
            if match:
                if current_trx: data.append(current_trx)
                # Mencari angka mutasi (biasanya ada 2-3 angka besar di baris itu)
                amounts = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', line)
                nominal = amounts[0] if len(amounts) > 0 else "0,00"
                saldo = amounts[-1] if len(amounts) > 1 else "0,00"
                
                # Panin: DB jika ada di posisi tengah, CR jika di kanan. 
                # Kita asumsikan CR dulu, nanti user bisa cek.
                current_trx = {
                    "Tanggal Transaksi": match.group(1).replace('-', '/'),
                    "Keterangan": line.replace(match.group(1), "").strip(),
                    "Cabang": "0", "Jumlah": f"{nominal} CR", "Saldo": saldo
                }
            elif current_trx and not any(x in line for x in ["Halaman", "Saldo", "Mata"]):
                current_trx["Keterangan"] += " " + line.strip()
                
    if current_trx: data.append(current_trx)
    return pd.DataFrame(data)

# --- PARSER BCA/MANDIRI ---
def parse_generic(pdf, year):
    data = []
    current_trx = None
    date_ptrn = re.compile(r'^(\d{2}/\d{2})\s')
    money_ptrn = re.compile(r'(\d{1,3}(?:,\d{3})*\.\d{2})')
    for page in pdf.pages:
        for line in (page.extract_text() or "").split('\n'):
            m = date_ptrn.match(line)
            if m:
                if current_trx: data.append(current_trx)
                moneys = money_ptrn.findall(line)
                current_trx = {
                    "Tanggal Transaksi": f"{m.group(1)}/{year}",
                    "Keterangan": line.strip(), "Cabang": "0",
                    "Jumlah": f"{moneys[0] if moneys else '0.00'} {'DB' if 'DB' in line.upper() else 'CR'}",
                    "Saldo": moneys[-1] if len(moneys)>1 else "0.00"
                }
            elif current_trx: current_trx["Keterangan"] += " " + line.strip()
    if current_trx: data.append(current_trx)
    return pd.DataFrame(data)

# --- EXECUTION ---
if uploaded_file and st.button("🚀 Convert Sekarang"):
    try:
        # Step 1: Coba buka PDF (Auto-decrypt)
        try:
            pdf = pdfplumber.open(uploaded_file, password=pdf_password if pdf_password else None)
        except:
            st.error("❌ Gagal membuka PDF. Jika file diproteksi, pastikan password benar.")
            st.stop()
            
        # Step 2: Pilih Parser
        with st.spinner("Menganalisa data..."):
            if bank_type == "BRI": df = parse_bri(pdf)
            elif bank_type == "Panin": df = parse_panin(pdf)
            else: df = parse_generic(pdf, tahun_input)
            
        pdf.close()
        
        # Step 3: Tampilkan Hasil
        if not df.empty:
            st.success(f"✅ Berhasil menarik {len(df)} transaksi!")
            st.dataframe(df)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 Download Excel", buffer.getvalue(), f"hasil_{bank_type.lower()}.xlsx")
        else:
            st.warning("⚠️ File terbuka tapi tidak ada transaksi yang terdeteksi. Cek format bank yang dipilih.")
            
    except Exception as e:
        st.error(f"Terjadi error sistem: {e}")

import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Multi-Bank Converter v6", page_icon="💰", layout="wide")
st.title("💰 Multi-Bank Statement Converter (Password Ready)")
st.info("Jika PDF Anda memiliki password (biasanya tanggal lahir atau nomor kartu), masukkan di kolom bawah.")

# --- PILIHAN BANK & PASSWORD ---
col1, col2 = st.columns(2)
with col1:
    bank_type = st.selectbox("1. Pilih Jenis Bank", ["BCA / Mandiri", "BRI", "Panin"])
    uploaded_file = st.file_uploader("2. Upload File PDF Rekening Koran", type="pdf")

with col2:
    pdf_password = st.text_input("3. Password PDF (Kosongkan jika tidak ada)", type="password")
    tahun_input = st.text_input("4. Tahun Laporan (Hanya BCA/Mandiri)", value="2026")

# --- MESIN PEMBERSIH ANGKA ---
def format_rp(val):
    if not val: return "0,00"
    s = str(val).strip().replace('\n', ' ')
    match = re.search(r'([\d.,]+)', s)
    return match.group(1) if match else "0,00"

def get_db_cr(debet, kredit):
    d = str(debet).strip().replace('.', '').replace(',', '')
    k = str(kredit).strip().replace('.', '').replace(',', '')
    if d and d not in ["000", "0", "None", "-", ""]: return f"{format_rp(debet)} DB"
    if k and k not in ["000", "0", "None", "-", ""]: return f"{format_rp(kredit)} CR"
    return "0,00 CR"

# --- PARSER BANK (Sama seperti v5 dengan tambahan password) ---
def parse_pdf(file_obj, bank, pswd, year):
    transactions = []
    # Membuka PDF dengan password jika disediakan
    with pdfplumber.open(file_obj, password=pswd if pswd else None) as pdf:
        for page in pdf.pages:
            if bank == "BRI":
                table = page.extract_table()
                if not table: continue
                for row in table:
                    if len(row) >= 6 and row[0] and re.search(r'\d{2}/\d{2}/\d{2}', str(row[0])):
                        date_part = str(row[0]).split(' ')[0]
                        d, m, y = date_part.split('/')
                        transactions.append({
                            "Tanggal Transaksi": f"{d}/{m}/20{y}",
                            "Keterangan": str(row[1]).replace('\n', ' '), "Cabang": str(row[2]),
                            "Jumlah": get_db_cr(row[3], row[4]), "Saldo": format_rp(row[5])
                        })
            elif bank == "Panin":
                table = page.extract_table()
                if not table: continue
                current_trx = None
                date_pattern = re.compile(r'(\d{1,2}-[a-zA-Z]{3}(?:-\d{4})?)')
                for row in table:
                    if len(row) < 6: continue
                    match = date_pattern.search(str(row[0]))
                    if match:
                        if current_trx: transactions.append(current_trx)
                        tgl = match.group(1).replace('-', '/')
                        if len(tgl) <= 6: tgl += f"/{year}"
                        current_trx = {
                            "Tanggal Transaksi": tgl, "Keterangan": str(row[2]).replace('\n', ' '),
                            "Cabang": "0", "Jumlah": get_db_cr(row[3], row[4]), "Saldo": format_rp(row[5])
                        }
                    elif current_trx and row[2] and not any(x in str(row[2]) for x in ["Halaman", "Saldo"]):
                        current_trx["Keterangan"] += " " + str(row[2]).replace('\n', ' ')
                if current_trx: transactions.append(current_trx)
            else: # BCA/Mandiri
                text = page.extract_text()
                if not text: continue
                date_pattern = re.compile(r'^(\d{2}/\d{2})\s')
                money_pattern = re.compile(r'(\d{1,3}(?:,\d{3})*\.\d{2})')
                current_trx = None
                for line in text.split('\n'):
                    date_match = date_pattern.match(line)
                    if date_match:
                        if current_trx: transactions.append(current_trx)
                        raw_date = date_match.group(1)
                        money_matches = money_pattern.findall(line)
                        nominal = money_matches[0] if money_matches else "0.00"
                        saldo = money_matches[-1] if len(money_matches) > 1 else "0.00"
                        type_label = "DB" if "DB" in line.upper() else "CR"
                        current_trx = {"Tanggal Transaksi": f"{raw_date}/{year}", "Keterangan": line.strip(), "Cabang": "0", "Jumlah": f"{nominal} {type_label}", "Saldo": saldo}
                    elif current_trx and not any(x in line for x in ["SALDO", "HALAMAN"]):
                        current_trx["Keterangan"] += " " + line.strip()
                if current_trx: transactions.append(current_trx)
    return pd.DataFrame(transactions)

# --- EKSEKUSI ---
if uploaded_file is not None:
    if st.button("🚀 Convert Sekarang"):
        with st.spinner("Sedang membuka PDF..."):
            try:
                df = parse_pdf(uploaded_file, bank_type, pdf_password, tahun_input)
                if not df.empty:
                    st.success(f"✅ Berhasil! Ditemukan {len(df)} transaksi.")
                    st.dataframe(df)
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False)
                    st.download_button("📥 Download Excel", data=buffer.getvalue(), file_name=f"hasil_{bank_type.lower()}.xlsx")
                else:
                    st.error("❌ Gagal membaca data. Cek apakah password sudah benar.")
            except Exception as e:
                st.error(f"Kesalahan: {e}")
                st.warning("Biasanya ini karena password salah atau PDF tidak bisa dibuka.")

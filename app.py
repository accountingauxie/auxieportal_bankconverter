import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Multi-Bank Converter v5", page_icon="💰", layout="wide")
st.title("💰 Multi-Bank Statement Converter (v5.0)")
st.markdown("Aplikasi konversi rekening koran dengan pembersihan data otomatis.")

# --- PILIHAN BANK ---
bank_type = st.selectbox("1. Pilih Jenis Bank", ["BCA / Mandiri", "BRI", "Panin"])
uploaded_file = st.file_uploader("2. Upload File PDF Rekening Koran", type="pdf")
tahun_input = st.text_input("3. Tahun Laporan (Hanya untuk BCA/Mandiri)", value="2026")

# --- MESIN PEMBERSIH ANGKA ---
def format_rp(val):
    if not val: return "0,00"
    s = str(val).strip().replace('\n', ' ')
    # Cari pola angka 1.000.000,00 atau 1,000,000.00
    match = re.search(r'([\d.,]+)', s)
    return match.group(1) if match else "0,00"

def get_db_cr(debet, kredit):
    d = str(debet).strip().replace('.', '').replace(',', '')
    k = str(kredit).strip().replace('.', '').replace(',', '')
    
    if d and d not in ["000", "0", "None", "-", ""]:
        return f"{format_rp(debet)} DB"
    if k and k not in ["000", "0", "None", "-", ""]:
        return f"{format_rp(kredit)} CR"
    return "0,00 CR"

# --- PARSER 1: BCA / MANDIRI ---
def parse_bca_mandiri(file_obj, tahun):
    transactions = []
    current_trx = None
    date_pattern = re.compile(r'^(\d{2}/\d{2})\s')
    money_pattern = re.compile(r'(\d{1,3}(?:,\d{3})*\.\d{2})')
    
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            for line in text.split('\n'):
                date_match = date_pattern.match(line)
                if date_match:
                    if current_trx: transactions.append(current_trx)
                    raw_date = date_match.group(1)
                    money_matches = money_pattern.findall(line)
                    nominal = money_matches[0] if money_matches else "0.00"
                    saldo = money_matches[-1] if len(money_matches) > 1 else "0.00"
                    type_label = "DB" if "DB" in line.upper() else "CR"
                    current_trx = {
                        "Tanggal Transaksi": f"{raw_date}/{tahun}",
                        "Keterangan": line.strip(), "Cabang": "0",
                        "Jumlah": f"{nominal} {type_label}", "Saldo": saldo
                    }
                elif current_trx and not any(x in line for x in ["SALDO", "HALAMAN"]):
                    current_trx["Keterangan"] += " " + line.strip()
        if current_trx: transactions.append(current_trx)
    return pd.DataFrame(transactions)

# --- PARSER 2: BRI ---
def parse_bri(file_obj):
    transactions = []
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            for row in table:
                # BRI: [Tgl, Uraian, Teller, Debet, Kredit, Saldo]
                if len(row) >= 6 and row[0] and re.search(r'\d{2}/\d{2}/\d{2}', str(row[0])):
                    date_part = str(row[0]).split(' ')[0]
                    d, m, y = date_part.split('/')
                    transactions.append({
                        "Tanggal Transaksi": f"{d}/{m}/20{y}",
                        "Keterangan": str(row[1]).replace('\n', ' '),
                        "Cabang": str(row[2]),
                        "Jumlah": get_db_cr(row[3], row[4]),
                        "Saldo": format_rp(row[5])
                    })
    return pd.DataFrame(transactions)

# --- PARSER 3: PANIN ---
def parse_panin(file_obj):
    transactions = []
    current_trx = None
    # Tanggal Panin: 15-Jan-2026 atau 15-Jan
    date_pattern = re.compile(r'(\d{1,2}-[a-zA-Z]{3}(?:-\d{4})?)')

    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            for row in table:
                # Kolom Panin: 0:Tgl Trx, 2:Detail, 3:Debet, 4:Kredit, 5:Saldo
                if len(row) < 6: continue
                tgl_txt = str(row[0])
                match = date_pattern.search(tgl_txt)
                
                if match:
                    if current_trx: transactions.append(current_trx)
                    tgl_final = match.group(1).replace('-', '/')
                    # Tambahkan tahun jika formatnya hanya DD-MMM
                    if len(tgl_final) <= 6: tgl_final += "/2026"
                    
                    current_trx = {
                        "Tanggal Transaksi": tgl_final,
                        "Keterangan": str(row[2]).replace('\n', ' '),
                        "Cabang": "0",
                        "Jumlah": get_db_cr(row[3], row[4]),
                        "Saldo": format_rp(row[5])
                    }
                elif current_trx and row[2] and not any(x in str(row[2]) for x in ["Halaman", "Saldo"]):
                    current_trx["Keterangan"] += " " + str(row[2]).replace('\n', ' ')
            
            if current_trx: transactions.append(current_trx)
    return pd.DataFrame(transactions)

# --- LOGIKA TOMBOL ---
if uploaded_file is not None:
    if st.button("🚀 Convert Sekarang"):
        with st.spinner(f"Mesin sedang menganalisa {bank_type}..."):
            try:
                if bank_type == "BRI": df = parse_bri(uploaded_file)
                elif bank_type == "Panin": df = parse_panin(uploaded_file)
                else: df = parse_bca_mandiri(uploaded_file, tahun_input)
                
                if not df.empty:
                    df = df.drop_duplicates()
                    st.success(f"✅ Sukses! Ditemukan {len(df)} transaksi.")
                    st.dataframe(df)
                    
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False)
                    st.download_button("📥 Download Excel", data=buffer.getvalue(), file_name=f"convert_{bank_type.lower()}.xlsx")
                else:
                    st.error("❌ Data tidak ditemukan. Pastikan Anda memilih jenis Bank yang sesuai.")
                    with st.expander("Bantuan Debugging"):
                        st.write("Isi teks terdeteksi di halaman 1:")
                        with pdfplumber.open(uploaded_file) as pdf:
                            st.text(pdf.pages[0].extract_text()[:1000])
            except Exception as e:
                st.error(f"Terjadi kesalahan teknis: {e}")
                st.warning("Tips: Coba cek apakah file PDF Anda memiliki password.")

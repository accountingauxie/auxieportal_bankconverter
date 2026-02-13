import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Multi-Bank Converter", page_icon="💰")
st.title("💰 Multi-Bank Statement Converter")
st.info("Pastikan Anda memilih bank yang sesuai dengan file yang diupload.")

# --- PILIHAN BANK ---
bank_type = st.selectbox("Pilih Format Bank", ["BCA / Mandiri", "BRI", "Panin"])
uploaded_file = st.file_uploader("Upload File PDF Rekening Koran", type="pdf")
tahun_laporan = st.text_input("Tahun (Hanya BCA/Mandiri)", value="2026")

# --- UTILITY: FORMAT JUMLAH ---
def format_jumlah_standard(debet, kredit):
    d = str(debet).strip().replace(',', '') if debet else ""
    k = str(kredit).strip().replace(',', '') if kredit else ""
    if d and d not in ["", "0.00", "0", "-", "None"]:
        return f"{debet} DB"
    if k and k not in ["", "0.00", "0", "-", "None"]:
        return f"{kredit} CR"
    return "0.00 CR"

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
                    current_trx = {"Tanggal Transaksi": f"{raw_date}/{tahun}", "Keterangan": line.strip(), "Cabang": "0", "Jumlah": f"{nominal} {type_label}", "Saldo": saldo}
                elif current_trx and "SALDO" not in line:
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
                if row[0] and re.search(r'\d{2}/\d{2}/\d{2}', str(row[0])):
                    date_part = row[0].split(' ')[0]
                    d, m, y = date_part.split('/')
                    transactions.append({"Tanggal Transaksi": f"{d}/{m}/20{y}", "Keterangan": str(row[1]).replace('\n', ' '), "Cabang": str(row[2]), "Jumlah": format_jumlah_standard(row[3], row[4]), "Saldo": row[5]})
    return pd.DataFrame(transactions)

# --- PARSER 3: PANIN (VERSI DIPERBAIKI) ---
def parse_panin(file_obj):
    transactions = []
    current_trx = None
    # Pola Tanggal Panin: 15-Jan-2026 atau 15-Jan
    date_pattern = re.compile(r'(\d{1,2}-[a-zA-Z]{3}(?:-\d{4})?)')
    
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            # Menggunakan text based untuk Panin karena lebih stabil
            lines = page.extract_text().split('\n')
            for line in lines:
                match = date_pattern.search(line)
                if match:
                    if current_trx: transactions.append(current_trx)
                    # Ambil nominal uang dari baris tersebut (pola angka dengan koma desimal)
                    money = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', line)
                    
                    # Logika Debet/Kredit Panin biasanya berdasarkan kolom, 
                    # di sini kita ambil angka pertama sebagai mutasi dan terakhir sebagai saldo
                    nominal = money[0] if len(money) > 0 else "0,00"
                    saldo = money[-1] if len(money) > 1 else "0,00"
                    
                    # Deteksi tipe berdasarkan posisi atau kata kunci jika ada
                    type_label = "CR" # Default Kredit di Panin jika tidak ada tanda khusus
                    
                    current_trx = {
                        "Tanggal Transaksi": match.group(1).replace('-', '/'),
                        "Keterangan": line.replace(match.group(1), "").strip(),
                        "Cabang": "0",
                        "Jumlah": f"{nominal} {type_label}",
                        "Saldo": saldo
                    }
                elif current_trx and not any(x in line for x in ["Halaman", "Saldo", "Mata Uang"]):
                    current_trx["Keterangan"] += " " + line.strip()
            
        if current_trx: transactions.append(current_trx)
    return pd.DataFrame(transactions)

# --- TOMBOL PROSES ---
if uploaded_file is not None:
    if st.button("🚀 Convert Sekarang"):
        with st.spinner(f"Memproses {bank_type}..."):
            try:
                if bank_type == "BRI": df = parse_bri(uploaded_file)
                elif bank_type == "Panin": df = parse_panin(uploaded_file)
                else: df = parse_bca_mandiri(uploaded_file, tahun_laporan)
                
                if not df.empty:
                    df = df[['Tanggal Transaksi', 'Keterangan', 'Cabang', 'Jumlah', 'Saldo']].drop_duplicates()
                    st.success("✅ Berhasil!")
                    st.dataframe(df.head(10))
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False)
                    st.download_button("📥 Download Excel", data=buffer.getvalue(), file_name=f"convert_{bank_type.lower()}.xlsx")
                else:
                    st.error("❌ Data tidak ditemukan. Pastikan 'Pilih Format Bank' sudah benar.")
            except Exception as e:
                st.error(f"Terjadi kesalahan: {e}")

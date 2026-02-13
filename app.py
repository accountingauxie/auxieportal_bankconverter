import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Multi-Bank Converter", page_icon="💰")
st.title("💰 Multi-Bank Statement Converter")
st.info("Pilih Bank sesuai file PDF agar sistem menggunakan mesin analisa yang tepat.")

# --- PILIHAN BANK ---
bank_type = st.selectbox("Pilih Format Bank", ["BCA / Mandiri", "BRI", "Panin"])
uploaded_file = st.file_uploader("Upload File PDF Rekening Koran", type="pdf")
tahun_input = st.text_input("Tahun Laporan (Hanya untuk BCA/Mandiri)", value="2026")

# --- FUNGSI PEMBANTU ---
def clean_amount(val):
    """Membersihkan teks angka agar bisa diproses"""
    if not val: return "0.00"
    # Hilangkan karakter non-angka kecuali titik dan koma
    clean = re.sub(r'[^\d.,]', '', str(val))
    return clean if clean else "0.00"

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
                # BRI Format: [Tanggal, Uraian, Teller, Debet, Kredit, Saldo]
                # Filter baris yang mengandung tanggal (dd/mm/yy)
                if row[0] and re.search(r'\d{2}/\d{2}/\d{2}', str(row[0])):
                    date_part = str(row[0]).split(' ')[0]
                    d, m, y = date_part.split('/')
                    
                    deb = clean_amount(row[3])
                    kre = clean_amount(row[4])
                    
                    # Logika penentuan DB/CR
                    if deb != "0.00" and deb != "":
                        jumlah_final = f"{deb} DB"
                    else:
                        jumlah_final = f"{kre} CR"
                    
                    transactions.append({
                        "Tanggal Transaksi": f"{d}/{m}/20{y}",
                        "Keterangan": str(row[1]).replace('\n', ' '),
                        "Cabang": str(row[2]),
                        "Jumlah": jumlah_final,
                        "Saldo": clean_amount(row[5])
                    })
    return pd.DataFrame(transactions)

# --- PARSER 3: PANIN ---
def parse_panin(file_obj):
    transactions = []
    current_trx = None
    # Pola Tanggal Panin: 15-Jan-2026 atau 15-Jan
    date_pattern = re.compile(r'(\d{1,2}-[a-zA-Z]{3}(?:-\d{4})?)')

    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            for row in table:
                # Panin Index: 0:Tgl, 1:Eff, 2:Detail, 3:Debit, 4:Kredit, 5:Saldo
                tgl = str(row[0]) if row[0] else ""
                match = date_pattern.search(tgl)
                
                if match:
                    if current_trx: transactions.append(current_trx)
                    
                    deb = clean_amount(row[3])
                    kre = clean_amount(row[4])
                    
                    if deb != "0.00" and deb != "":
                        jumlah_final = f"{deb} DB"
                    else:
                        jumlah_final = f"{kre} CR"
                        
                    current_trx = {
                        "Tanggal Transaksi": match.group(1).replace('-', '/'),
                        "Keterangan": str(row[2]).replace('\n', ' '),
                        "Cabang": "0",
                        "Jumlah": jumlah_final,
                        "Saldo": clean_amount(row[5])
                    }
                elif current_trx and row[2]:
                    # Gabungkan keterangan jika berlanjut ke baris bawah
                    current_trx["Keterangan"] += " " + str(row[2]).replace('\n', ' ')
            
            if current_trx: transactions.append(current_trx)
    return pd.DataFrame(transactions).drop_duplicates()

# --- TOMBOL PROSES ---
if uploaded_file is not None:
    if st.button("🚀 Convert Sekarang"):
        with st.spinner(f"Menganalisa format {bank_type}..."):
            try:
                if bank_type == "BRI":
                    df = parse_bri(uploaded_file)
                elif bank_type == "Panin":
                    df = parse_panin(uploaded_file)
                else:
                    df = parse_bca_mandiri(uploaded_file, tahun_input)
                
                if not df.empty:
                    st.success(f"✅ Berhasil! Menemukan {len(df)} transaksi.")
                    # Reorder kolom sesuai standar output Anda
                    df = df[['Tanggal Transaksi', 'Keterangan', 'Cabang', 'Jumlah', 'Saldo']]
                    st.dataframe(df.head(20))
                    
                    # Sediakan tombol download
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False)
                    st.download_button("📥 Download Excel", data=buffer.getvalue(), file_name=f"hasil_{bank_type.lower()}.xlsx")
                else:
                    st.error("❌ Data tidak ditemukan. Pastikan Anda memilih jenis bank yang benar.")
            except Exception as e:
                st.error(f"Terjadi kesalahan saat membaca file: {e}")

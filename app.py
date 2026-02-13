import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Multi-Bank Converter v4", page_icon="💰")
st.title("💰 Multi-Bank Statement Converter")
st.markdown("---")

# --- PILIHAN BANK ---
bank_type = st.selectbox("1. Pilih Format Bank", ["BCA / Mandiri", "BRI", "Panin"])
uploaded_file = st.file_uploader("2. Upload File PDF Rekening Koran", type="pdf")
tahun_input = st.text_input("3. Tahun Laporan (Penting untuk BCA/Mandiri)", value="2026")

# --- UTILITY: MEMBERSIHKAN ANGKA ---
def clean_amount_id(val):
    """Membersihkan format angka Indonesia 1.234.567,89"""
    if not val or val == "None": return "0,00"
    s = str(val).strip().replace(' ', '')
    # Jika angka hanya mengandung digit, titik, dan koma
    match = re.search(r'(\d{1,3}(?:\.\d{3})*,\d{2})', s)
    if match: return match.group(1)
    # Fallback untuk format Inggris 1,234,567.89
    match_en = re.search(r'(\d{1,3}(?:,\d{3})*\.\d{2})', s)
    if match_en: return match_en.group(1).replace(',', 'X').replace('.', ',').replace('X', '.')
    return s if s else "0,00"

# --- PARSER 1: BCA / MANDIRI ---
def parse_bca_mandiri(file_obj, tahun):
    transactions = []
    current_trx = None
    date_pattern = re.compile(r'^(\d{2}/\d{2})\s')
    # Mencari nominal format Inggris (BCA/Mandiri biasanya pakai . untuk desimal)
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
            # Gunakan pengaturan tabel yang lebih longgar untuk BRI
            table = page.extract_table(table_settings={
                "vertical_strategy": "text", 
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
            })
            if not table: continue
            for row in table:
                # BRI: [Tgl, Uraian, Teller, Debet, Kredit, Saldo]
                # Filter baris yang berisi tanggal (01/01/26)
                if len(row) >= 6 and row[0] and re.search(r'\d{2}/\d{2}/\d{2}', str(row[0])):
                    date_part = str(row[0]).split(' ')[0]
                    d, m, y = date_part.split('/')
                    
                    deb = str(row[3]).strip() if row[3] else "0.00"
                    kre = str(row[4]).strip() if row[4] else "0.00"
                    
                    type_label = "DB" if (deb != "0.00" and deb != "0" and deb != "") else "CR"
                    nominal = deb if type_label == "DB" else kre

                    transactions.append({
                        "Tanggal Transaksi": f"{d}/{m}/20{y}",
                        "Keterangan": str(row[1]).replace('\n', ' '),
                        "Cabang": str(row[2]),
                        "Jumlah": f"{nominal} {type_label}",
                        "Saldo": str(row[5])
                    })
    return pd.DataFrame(transactions)

# --- PARSER 3: PANIN ---
def parse_panin(file_obj):
    transactions = []
    current_trx = None
    # Pola Tanggal Panin: 15-Jan-2026
    date_pattern = re.compile(r'(\d{1,2}-[a-zA-Z]{3}-\d{4})')

    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            # Panin lebih stabil menggunakan ekstraksi tabel paksa
            table = page.extract_table()
            if not table: continue
            for row in table:
                if len(row) < 6: continue
                tgl = str(row[0])
                match = date_pattern.search(tgl)
                
                if match:
                    if current_trx: transactions.append(current_trx)
                    
                    deb = clean_amount_id(row[3])
                    kre = clean_amount_id(row[4])
                    
                    type_label = "DB" if (deb != "0,00" and deb != "") else "CR"
                    nominal = deb if type_label == "DB" else kre
                        
                    current_trx = {
                        "Tanggal Transaksi": match.group(1).replace('-', '/'),
                        "Keterangan": str(row[2]).replace('\n', ' '),
                        "Cabang": "0",
                        "Jumlah": f"{nominal} {type_label}",
                        "Saldo": clean_amount_id(row[5])
                    }
                elif current_trx and row[2] and not re.search(r'Halaman|Saldo|Mata Uang', str(row[2])):
                    current_trx["Keterangan"] += " " + str(row[2]).replace('\n', ' ')
            
            if current_trx: transactions.append(current_trx)
    return pd.DataFrame(transactions).drop_duplicates()

# --- EKSEKUSI ---
if uploaded_file is not None:
    if st.button("🚀 Convert Sekarang"):
        with st.spinner(f"Mesin sedang membaca PDF {bank_type}..."):
            try:
                if bank_type == "BRI": df = parse_bri(uploaded_file)
                elif bank_type == "Panin": df = parse_panin(uploaded_file)
                else: df = parse_bca_mandiri(uploaded_file, tahun_input)
                
                if not df.empty:
                    st.success(f"✅ Sukses! Menemukan {len(df)} transaksi.")
                    df_final = df[['Tanggal Transaksi', 'Keterangan', 'Cabang', 'Jumlah', 'Saldo']]
                    st.dataframe(df_final)
                    
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df_final.to_excel(writer, index=False)
                    st.download_button("📥 Download Excel", data=buffer.getvalue(), file_name=f"hasil_{bank_type.lower()}.xlsx")
                else:
                    st.error("❌ Data tidak ditemukan. Cek apakah Anda salah memilih jenis Bank.")
                    # Debugging untuk user
                    with st.expander("Lihat Teks Mentah (Hanya untuk pengecekan)"):
                        with pdfplumber.open(uploaded_file) as pdf:
                            st.text(pdf.pages[0].extract_text()[:500])
            except Exception as e:
                st.error(f"Terjadi kesalahan teknis: {e}")

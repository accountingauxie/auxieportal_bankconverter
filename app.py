import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Multi-Bank Converter", page_icon="💰")
st.title("💰 Multi-Bank Statement Converter")
st.write("Satu aplikasi untuk berbagai format bank. Hasil output seragam.")

# --- PILIHAN BANK ---
bank_type = st.selectbox("Pilih Format Bank", ["BCA / Mandiri", "BRI", "Panin"])
uploaded_file = st.file_uploader("Upload File PDF Rekening Koran", type="pdf")
tahun_laporan = st.text_input("Tahun Laporan (Hanya untuk BCA/Mandiri)", value="2026")

# --- UTILITY: FORMAT JUMLAH ---
def format_jumlah_standard(debet, kredit):
    """Menyertakan DB/CR pada nominal"""
    if debet and str(debet).strip() not in ["", "0.00", "0", "-"]:
        return f"{debet} DB"
    if kredit and str(kredit).strip() not in ["", "0.00", "0", "-"]:
        return f"{kredit} CR"
    return "0.00 CR"

# --- PARSER 1: BCA / MANDIRI (Text Based) ---
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
                        "Keterangan": line.strip(),
                        "Cabang": "0",
                        "Jumlah": f"{nominal} {type_label}",
                        "Saldo": saldo
                    }
                else:
                    if current_trx and "SALDO" not in line:
                        current_trx["Keterangan"] += " " + line.strip()
        if current_trx: transactions.append(current_trx)
    return pd.DataFrame(transactions)

# --- PARSER 2: BRI (Table Based) ---
def parse_bri(file_obj):
    transactions = []
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            for row in table:
                # BRI: [Tgl, Uraian, Teller, Debet, Kredit, Saldo]
                if row[0] and re.search(r'\d{2}/\d{2}/\d{2}', row[0]):
                    date_part = row[0].split(' ')[0]
                    d, m, y = date_part.split('/')
                    transactions.append({
                        "Tanggal Transaksi": f"{d}/{m}/20{y}",
                        "Keterangan": row[1].replace('\n', ' ') if row[1] else "",
                        "Cabang": row[2] if row[2] else "0",
                        "Jumlah": format_jumlah_standard(row[3], row[4]),
                        "Saldo": row[5]
                    })
    return pd.DataFrame(transactions)

# --- PARSER 3: PANIN (Table Based with Multi-line) ---
def parse_panin(file_obj):
    transactions = []
    current_trx = None
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            for row in table:
                # Panin index: 0:Tgl Trx, 1:Tgl Efektif, 2:Detail, 3:Debit, 4:Kredit, 5:Saldo
                tgl_trx = row[0] if row[0] else ""
                
                # Jika ada tanggal, berarti baris baru
                if re.search(r'\d{2}-[a-zA-Z]{3}-\d{4}', tgl_trx):
                    if current_trx: transactions.append(current_trx)
                    current_trx = {
                        "Tanggal Transaksi": tgl_trx.replace('-', '/'), # Standardize to /
                        "Keterangan": row[2].replace('\n', ' ') if row[2] else "",
                        "Cabang": "0", # Panin di image tidak eksplisit kolom cabang
                        "Jumlah": format_jumlah_standard(row[3], row[4]),
                        "Saldo": row[5]
                    }
                # Jika tanggal kosong tapi detail ada, berarti lanjutan keterangan
                elif current_trx and row[2]:
                    current_trx["Keterangan"] += " " + row[2].replace('\n', ' ')
            
            if current_trx: transactions.append(current_trx)
    return pd.DataFrame(transactions)

# --- TOMBOL PROSES ---
if uploaded_file is not None:
    if st.button("🚀 Convert Sekarang"):
        with st.spinner(f"Memproses format {bank_type}..."):
            try:
                if bank_type == "BRI":
                    df = parse_bri(uploaded_file)
                elif bank_type == "Panin":
                    df = parse_panin(uploaded_file)
                else:
                    df = parse_bca_mandiri(uploaded_file, tahun_laporan)
                
                if not df.empty:
                    # Final formatting: Pastikan kolom seragam
                    final_cols = ['Tanggal Transaksi', 'Keterangan', 'Cabang', 'Jumlah', 'Saldo']
                    df = df[final_cols].drop_duplicates()

                    st.success(f"✅ Berhasil Ekstrak Data {bank_type}!")
                    st.write("Preview data:")
                    st.dataframe(df.head(10))
                    
                    # --- DOWNLOAD EXCEL ---
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False)
                    
                    st.download_button(
                        label="📥 Download Hasil (.xlsx)",
                        data=buffer.getvalue(),
                        file_name=f"convert_{bank_type.lower()}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.error("❌ Tidak ada data yang ditemukan. Pastikan file PDF benar.")
            except Exception as e:
                st.error(f"Terjadi kesalahan teknis: {e}")

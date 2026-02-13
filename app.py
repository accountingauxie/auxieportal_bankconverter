import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Bank Converter", page_icon="💰")
st.title("💰 Aplikasi Konversi Bank Statement")
st.write("Upload PDF Rekening Koran -> Klik Convert -> Download Excel")

# --- INPUT USER ---
uploaded_file = st.file_uploader("Upload File PDF di sini", type="pdf")
tahun_laporan = st.text_input("Tahun Laporan (YYYY)", value="2026")

# --- FUNGSI CONVERTER ---
def convert_pdf(file_obj, tahun):
    transactions = []
    current_trx = None
    
    # Regex Patterns (Pola pencarian teks)
    date_pattern = re.compile(r'^(\d{2}/\d{2})\s')
    money_pattern = re.compile(r'(\d{1,3}(?:,\d{3})*\.\d{2})')
    branch_pattern = re.compile(r'\b(\d{4})\b')

    try:
        with pdfplumber.open(file_obj) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text: continue
                
                lines = text.split('\n')
                for line in lines:
                    # Cek apakah baris dimulai dengan Tanggal
                    date_match = date_pattern.match(line)
                    
                    if date_match:
                        # Simpan transaksi sebelumnya jika ada
                        if current_trx: transactions.append(current_trx)
                        
                        # --- AMBIL DATA ---
                        raw_date = date_match.group(1)
                        formatted_date = f"{raw_date}/{tahun}"
                        
                        # Cari Uang
                        money_matches = money_pattern.findall(line)
                        nominal = money_matches[0] if money_matches else "0.00"
                        saldo = money_matches[-1] if len(money_matches) > 1 else "0.00"
                        
                        # Cek DB/CR
                        type_label = "DB" if "DB" in line.upper() else "CR"
                        formatted_jumlah = f"{nominal} {type_label}"
                        
                        # Cari Cabang
                        branch_match = branch_pattern.search(line)
                        cabang = branch_match.group(1) if branch_match else "0"
                        
                        # Bersihkan Keterangan
                        desc = line
                        for item in [raw_date, nominal, saldo, "DB", "Hb", "Cr"]: 
                            desc = desc.replace(item, "")
                        if cabang != "0": desc = desc.replace(cabang, "")
                        desc = re.sub(r'\s+', ' ', desc).strip()

                        current_trx = {
                            "Tanggal Transaksi": formatted_date,
                            "Keterangan": desc,
                            "Cabang": cabang,
                            "Jumlah": formatted_jumlah,
                            "Saldo": saldo
                        }
                    else:
                        # Baris Lanjutan (Detail)
                        if current_trx and "SALDO" not in line and "HALAMAN" not in line:
                            current_trx["Keterangan"] += " " + line.strip()

            # Simpan transaksi terakhir
            if current_trx: transactions.append(current_trx)
            
        return pd.DataFrame(transactions)
    except Exception as e:
        return pd.DataFrame()

# --- TOMBOL PROSES ---
if uploaded_file is not None:
    if st.button("🚀 Convert Sekarang"):
        with st.spinner("Sedang memproses PDF..."):
            try:
                df = convert_pdf(uploaded_file, tahun_laporan)
                
                if not df.empty:
                    # Rapikan Kolom
                    cols = ['Tanggal Transaksi', 'Keterangan', 'Cabang', 'Jumlah', 'Saldo']
                    # Pastikan kolom ada
                    final_cols = [c for c in cols if c in df.columns]
                    df = df[final_cols]

                    st.success("✅ Berhasil! Data ditemukan.")
                    st.write("Preview 5 data teratas:")
                    st.dataframe(df.head())
                    
                    # --- DOWNLOAD EXCEL ---
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False)
                    
                    st.download_button(
                        label="📥 Download File Excel",
                        data=buffer.getvalue(),
                        file_name="hasil_convert.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.error("❌ Data tidak ditemukan atau format PDF tidak cocok.")
            except Exception as e:
                st.error(f"Terjadi kesalahan: {e}")

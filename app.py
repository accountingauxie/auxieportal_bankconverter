import streamlit as st
import pdfplumber
import pandas as pd
import re
import os

# --- CONFIG ---
st.set_page_config(page_title="Accounting CSV Converter", layout="wide")
st.title("💰 Bank to CSV Converter (Accounting Format)")
st.markdown("Output format CSV: `*Date`, `*Amount`, `Payee`, `Description`, `Reference`, `Check Number`")

# --- UI ---
col1, col2 = st.columns(2)
with col1:
    bank_type = st.selectbox("1. Pilih Bank", ["BCA", "BRI", "Panin"])
    uploaded_file = st.file_uploader("2. Upload PDF", type="pdf")
with col2:
    pdf_password = st.text_input("3. Password (Jika ada)", type="password")
    tahun_input = st.text_input("4. Tahun (Khusus BCA/Mandiri)", value="2026")

# --- UTILITY: KONVERSI KE ANGKA MURNI ---
def parse_number(text_val, is_indo_format=True):
    if not text_val: return 0.0
    clean = str(text_val).strip()
    # Bersihkan simbol mata uang
    clean = clean.replace('IDR', '').replace('Rp', '').strip()

    if is_indo_format:
        # Format Indo: 10.000,00 -> Hapus titik, ganti koma jadi titik
        clean = clean.replace('.', '').replace(',', '.')
    else:
        # Format US (BRI): 10,000.00 -> Hapus koma
        clean = clean.replace(',', '')
        
    try:
        return float(clean)
    except:
        return 0.0

# --- PARSER BRI (METODE TEXT - LEBIH STABIL) ---
def parse_bri(pdf):
    data = []
    # Regex mendeteksi tanggal di awal baris: 01/01/26
    date_start_pattern = re.compile(r'^(\d{2}/\d{2}/\d{2,4})')
    
    for page in pdf.pages:
        # Ambil teks mentah, menjaga tata letak visual
        text = page.extract_text(layout=True)
        if not text: continue
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            # 1. Cek apakah baris diawali tanggal valid
            date_match = date_start_pattern.search(line)
            if date_match:
                raw_date = date_match.group(1)
                
                # 2. Cari angka format uang di baris ini
                # Regex ini mencari pola angka seperti: 26,250.00 atau 0.00
                # Mendukung format 1,000.00 (BRI)
                money_matches = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2})', line)
                
                # Logika BRI: Baris transaksi pasti punya minimal 3 kolom angka di akhir
                # Urutan dari belakang: [Saldo, Kredit, Debet]
                if len(money_matches) >= 3:
                    saldo_txt = money_matches[-1]
                    kredit_txt = money_matches[-2]
                    debet_txt = money_matches[-3]
                    
                    # Parse angka (BRI pakai format US: Koma=Ribuan, Titik=Desimal)
                    debet_val = parse_number(debet_txt, is_indo_format=False)
                    kredit_val = parse_number(kredit_txt, is_indo_format=False)
                    
                    nominal = 0.0
                    jenis = "CR"

                    if debet_val > 0:
                        nominal = debet_val
                        jenis = "DB"
                    else:
                        nominal = kredit_val
                        jenis = "CR"

                    # 3. Ambil Deskripsi
                    # Caranya: Hapus Tanggal dari depan, Hapus Angka dari belakang
                    # Sisa teks di tengah adalah Deskripsi + Teller ID
                    
                    # Hapus tanggal
                    temp_line = line.replace(raw_date, "", 1)
                    
                    # Hapus angka-angka transaksi dari string (ambil 3 angka terakhir yg ditemukan)
                    for m in [debet_txt, kredit_txt, saldo_txt]:
                        # replace dari kanan (reverse) agar aman jika ada angka sama di deskripsi
                        temp_line = temp_line.rsplit(m, 1)[0]
                    
                    clean_desc = temp_line.strip()
                    
                    # 4. Fix Tahun Tanggal (26 -> 2026)
                    parts = raw_date.split('/')
                    if len(parts) == 3 and len(parts[2]) == 2:
                        parts[2] = "20" + parts[2]
                    final_date = "/".join(parts)

                    data.append({
                        "Tanggal": final_date,
                        "Keterangan": clean_desc,
                        "Nominal": nominal,
                        "Jenis": jenis
                    })

    return pd.DataFrame(data)

# --- PARSER PANIN ---
def parse_panin(pdf):
    data = []
    current_trx = None
    date_regex = re.compile(r'(\d{1,2}-[a-zA-Z]{3}-\d{4})')
    saldo_terakhir = None
    
    def parse_panin_num(txt):
        if not txt: return 0.0
        is_neg = '(' in txt and ')' in txt
        clean = txt.replace('(', '').replace(')', '').replace('.', '').replace(',', '.')
        try:
            return -float(clean) if is_neg else float(clean)
        except:
            return 0.0
    
    for page in pdf.pages:
        text = page.extract_text()
        if not text: continue
        for line in text.split('\n'):
            if any(x in line.upper() for x in ["RINGKASAN AKUN", "MUTASI DEBIT", "MUTASI KREDIT"]):
                if current_trx: 
                    data.append(current_trx)
                    current_trx = None
                continue 
                
            if "SALDO" in line.upper():
                amounts = re.findall(r'(\(?\d{1,3}(?:\.\d{3})*,\d{2}\)?)', line)
                if amounts and any(x in line.upper() for x in ["AWAL", "LALU", "PINDAH"]):
                    saldo_terakhir = parse_panin_num(amounts[-1]) 
            
            match = date_regex.search(line)
            if match:
                if current_trx: data.append(current_trx)
                
                amounts = re.findall(r'(\(?\d{1,3}(?:\.\d{3})*,\d{2}\)?)', line)
                if len(amounts) >= 2:
                    nominal_txt, saldo_txt = amounts[0], amounts[-1]
                elif len(amounts) == 1:
                    nominal_txt, saldo_txt = amounts[0], amounts[0]
                else:
                    nominal_txt, saldo_txt = "0,00", "0,00"
                    
                nominal_float = abs(parse_panin_num(nominal_txt))
                saldo_float = parse_panin_num(saldo_txt)
                
                jenis = "CR"
                if saldo_terakhir is not None:
                    if abs(saldo_terakhir - nominal_float - saldo_float) < 1.0:
                        jenis = "DB"
                    elif abs(saldo_terakhir + nominal_float - saldo_float) < 1.0:
                        jenis = "CR"
                    else:
                        if any(k in line.upper() for k in ["RTGS", "PAJAK", "TARIK", "BIAYA", "CHG", "CHARGE", "OD CHG"]):
                            jenis = "DB"
                else:
                    if any(k in line.upper() for k in ["RTGS", "PAJAK", "TARIK", "BIAYA", "TRF KE", "CHG", "CHARGE", "OD CHG"]):
                        jenis = "DB"
                
                saldo_terakhir = saldo_float
                
                raw_desc = line.replace(match.group(1), "")
                clean_desc = re.sub(r'\(?\d{1,3}(?:\.\d{3})*,\d{2}\)?', '', raw_desc).strip()
                
                current_trx = {
                    "Tanggal": match.group(1).replace('-', '/'),
                    "Keterangan": clean_desc,
                    "Nominal": nominal_float,
                    "Jenis": jenis
                }
            elif current_trx:
                if not any(x in line.upper() for x in ["HALAMAN", "SALDO", "MATA", "TGL. TRANSAKSI"]):
                    clean_line = re.sub(r'\(?\d{1,3}(?:\.\d{3})*,\d{2}\)?', '', line).strip()
                    if clean_line:
                        current_trx["Keterangan"] += " " + clean_line
                
    if current_trx: data.append(current_trx)
    return pd.DataFrame(data)

# --- PARSER BCA/MANDIRI ---
def parse_generic(pdf, year):
    data = []
    current_trx = None
    date_ptrn = re.compile(r'^(\d{2}/\d{2})\s')
    money_ptrn = re.compile(r'(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})')
    
    for page in pdf.pages:
        for line in (page.extract_text() or "").split('\n'):
            m = date_ptrn.match(line)
            if m:
                if current_trx: data.append(current_trx)
                moneys = money_ptrn.findall(line)
                nominal_txt = moneys[0] if moneys else "0.00"
                
                current_trx = {
                    "Tanggal": f"{m.group(1)}/{year}",
                    "Keterangan": line.strip(), 
                    "Nominal": parse_number(nominal_txt, is_indo_format=False), 
                    "Jenis": "DB" if "DB" in line.upper() else "CR"
                }
            elif current_trx:
                if not any(keyword in line.upper() for keyword in ["SALDO", "MUTASI", "HALAMAN", "PAGE"]):
                    current_trx["Keterangan"] += " " + line.strip()
                    
    if current_trx: data.append(current_trx)
    return pd.DataFrame(data)

# --- EXECUTION ---
if uploaded_file and st.button("🚀 Convert ke CSV"):
    try:
        try:
            pdf = pdfplumber.open(uploaded_file, password=pdf_password if pdf_password else None)
        except:
            st.error("❌ Gagal buka PDF. Cek Password.")
            st.stop()
            
        with st.spinner("Sedang memproses..."):
            if bank_type == "BRI": df = parse_bri(pdf)
            elif bank_type == "Panin": df = parse_panin(pdf)
            else: df = parse_generic(pdf, tahun_input)
        pdf.close()
        
        if not df.empty:
            
            # --- FILTER SALDO AWAL / AKHIR & SALDO 0 ---
            kata_kunci_blokir = ["SALDO AWAL", "SALDO AKHIR", "SALDO LALU", "BEGINNING BALANCE"]
            
            csv_data = []
            transaksi_valid = 0
            
            for index, row in df.iterrows():
                ket_upper = str(row['Keterangan']).upper()
                
                is_saldo_summary = any(k in ket_upper for k in kata_kunci_blokir)
                try:
                    is_nominal_valid = float(row['Nominal']) > 0
                except:
                    is_nominal_valid = False
                
                if not is_saldo_summary and is_nominal_valid:
                    amount = row['Nominal']
                    # LOGIKA CSV: Debit = Negatif, Kredit = Positif
                    if row['Jenis'] == 'DB':
                        amount = -abs(amount)
                    else:
                        amount = abs(amount)
                    
                    csv_data.append({
                        "*Date": row['Tanggal'],
                        "*Amount": amount,  
                        "Payee": "",        
                        "Description": row['Keterangan'],
                        "Reference": "",     
                        "Check Number": ""   
                    })
                    transaksi_valid += 1
            
            df_final = pd.DataFrame(csv_data)
            
            st.success(f"✅ Berhasil! Membaca {len(df)} baris (Tersaring {transaksi_valid} transaksi valid).")
            
            st.dataframe(df_final.style.format({"*Amount": "{:,.2f}"}))
            
            # --- DOWNLOAD BUTTON ---
            csv_string = df_final.to_csv(index=False, float_format='%.2f').encode('utf-8')
            
            original_filename, _ = os.path.splitext(uploaded_file.name)
            output_filename = f"{original_filename}.csv"
            
            st.download_button(
                label="📥 Download CSV",
                data=csv_string,
                file_name=output_filename,
                mime="text/csv"
            )
        else:
            st.warning("⚠️ Data kosong. Format PDF BRI ini mungkin tidak memiliki garis tabel. Coba lagi.")
            
    except Exception as e:
        st.error(f"Error System: {e}")

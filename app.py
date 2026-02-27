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

# --- PARSER BRI (REVISI KETERANGAN & MULTILINE) ---
def parse_bri(pdf):
    data = []
    current_trx = None
    
    # Regex untuk mendeteksi awal baris: Tanggal + Waktu (contoh: 01/01/26 13:15:37)
    date_time_pattern = re.compile(r'^(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})')
    # Regex untuk nominal uang format US (contoh: 1,000.00 atau 0.00)
    money_pattern = re.compile(r'(\d{1,3}(?:,\d{3})*\.\d{2})')
    
    for page in pdf.pages:
        # Gunakan layout=False agar teks yang panjang / turun ke bawah (multiline) lebih mudah ditangkap
        text = page.extract_text(layout=False)
        if not text: continue
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Skip baris header tabel
            if any(x in line for x in ["Tanggal Transaksi", "Transaction Date", "Saldo", "Balance", "Uraian Transaksi", "Halaman", "Page"]):
                continue

            # 1. Cek apakah baris diawali Tanggal & Waktu
            dt_match = date_time_pattern.search(line)
            
            if dt_match:
                # Jika ada transaksi sebelumnya yang sedang direkam, simpan dulu
                if current_trx:
                    data.append(current_trx)
                    
                raw_date = dt_match.group(1)
                raw_time = dt_match.group(2)
                
                # 2. Cari angka format uang di baris ini
                money_matches = money_pattern.findall(line)
                
                # Logika BRI: Baris utama pasti punya 3 angka (Debet, Kredit, Saldo)
                if len(money_matches) >= 3:
                    saldo_txt = money_matches[-1]
                    kredit_txt = money_matches[-2]
                    debet_txt = money_matches[-3]
                    
                    debet_val = parse_number(debet_txt, is_indo_format=False)
                    kredit_val = parse_number(kredit_txt, is_indo_format=False)
                    
                    nominal = debet_val if debet_val > 0 else kredit_val
                    jenis = "DB" if debet_val > 0 else "CR"
                    
                    # 3. Ambil Deskripsi Murni
                    # a. Hapus Tanggal dan Waktu dari depan
                    temp_line = line.replace(f"{raw_date} {raw_time}", "", 1).strip()
                    
                    # b. Hapus ke-3 nominal uang dari belakang
                    for m in [saldo_txt, kredit_txt, debet_txt]:
                        temp_line = temp_line.rsplit(m, 1)[0].strip()
                        
                    # c. Hapus Teller ID (kata terakhir yang tersisa sebelum angka uang, misal: BRIMDBT atau 8888018)
                    parts = temp_line.rsplit(' ', 1)
                    if len(parts) == 2:
                        clean_desc = parts[0].strip()
                    else:
                        clean_desc = temp_line.strip()
                        
                    # 4. Fix Tahun Tanggal (26 -> 2026)
                    date_parts = raw_date.split('/')
                    if len(date_parts) == 3 and len(date_parts[2]) == 2:
                        date_parts[2] = "20" + date_parts[2]
                    final_date = "/".join(date_parts)
                    
                    current_trx = {
                        "Tanggal": final_date,
                        "Keterangan": clean_desc,
                        "Nominal": nominal,
                        "Jenis": jenis
                    }
            elif current_trx:
                # --- PROSES MULTILINE ---
                # Jika tidak ada pola Tanggal+Waktu di awal baris, ini adalah lanjutan Uraian Transaksi
                # Contoh: tulisan "ESB:NBMB:0001500F:954688861644"
                
                clean_line = " ".join(line.split())
                if clean_line:
                    current_trx["Keterangan"] += " " + clean_line

    if current_trx:
        data.append(current_trx)
        
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

# --- PARSER BCA/MANDIRI (REVISI KETERANGAN) ---
def parse_generic(pdf, year):
    data = []
    current_trx = None
    # Pola mendeteksi tanggal di awal baris (contoh: 01/01)
    date_ptrn = re.compile(r'^(\d{2}/\d{2})\s')
    # Pola mendeteksi angka uang, mendukung minus untuk saldo (contoh: 14,530,000.00 atau -714,011,582.83)
    money_ptrn = re.compile(r'-?\d{1,3}(?:,\d{3})*\.\d{2}')
    
    for page in pdf.pages:
        text = page.extract_text()
        if not text: continue
        
        for line in text.split('\n'):
            line = line.strip()
            if not line: continue

            m = date_ptrn.match(line)
            if m:
                # Jika ada transaksi sebelumnya yang sedang direkam, simpan dulu
                if current_trx: data.append(current_trx)
                
                raw_date = m.group(1)
                moneys = money_ptrn.findall(line)
                
                # Nominal mutasi biasanya adalah angka uang pertama yang muncul di baris itu
                nominal_txt = moneys[0] if moneys else "0.00"
                
                # --- PROSES MEMBERSIHKAN KETERANGAN ---
                # 1. Hapus tanggal dari awal kalimat
                clean_desc = line.replace(raw_date, "", 1).strip()
                
                # 2. Hapus semua angka format uang (Mutasi & Saldo) beserta minusnya dari teks keterangan
                for money in moneys:
                    clean_desc = clean_desc.replace(money, "")
                    
                # 3. Hapus tulisan "DB" atau "CR" yang berdiri sendiri (biasanya penanda debit di BCA)
                clean_desc = re.sub(r'\b(DB|CR)\b', '', clean_desc)
                
                # 4. Hapus kode cabang (CBG) berupa 4 digit angka di akhir teks (contoh: 7910)
                clean_desc = re.sub(r'\s+\d{4}\s*$', '', clean_desc)
                
                # Rapikan spasi berlebih
                clean_desc = " ".join(clean_desc.split())

                current_trx = {
                    "Tanggal": f"{raw_date}/{year}",
                    "Keterangan": clean_desc, 
                    "Nominal": parse_number(nominal_txt, is_indo_format=False), 
                    "Jenis": "DB" if "DB" in line.upper() else "CR"
                }
            elif current_trx:
                # Menangkap teks keterangan yang turun ke baris bawah (multiline)
                # Pastikan ini bukan baris header atau footer tabel
                if not any(keyword in line.upper() for keyword in ["SALDO", "MUTASI", "HALAMAN", "PAGE", "KETERANGAN", "TANGGAL", "REKENING"]):
                    clean_line = line
                    
                    # Buang jika ada angka nominal yang nyasar ke baris kedua
                    moneys_in_line = money_ptrn.findall(clean_line)
                    for money in moneys_in_line:
                        clean_line = clean_line.replace(money, "")
                    
                    # Bersihkan sisa-sisa teks yang tidak perlu
                    clean_line = re.sub(r'\b(DB|CR)\b', '', clean_line)
                    clean_line = " ".join(clean_line.split())
                    
                    if clean_line:
                        current_trx["Keterangan"] += " " + clean_line
                        
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

import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

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
    tahun_input = st.text_input("4. Tahun (Hanya BCA/Mandiri)", value="2026")

# --- UTILITY: KONVERSI KE ANGKA MURNI ---
def parse_number(text_val, is_indo_format=True):
    if not text_val: return 0.0
    clean = str(text_val).strip()
    
    if is_indo_format:
        # Format PANIN: 30.000,00 -> 30000.00
        clean = clean.replace('.', '').replace(',', '.')
    else:
        # Format BCA / BRI: 14,530,000.00 -> 14530000.00
        clean = clean.replace(',', '')
        
    try:
        return float(clean)
    except:
        return 0.0

# --- UTILITY: DETEKSI PAYEE (Otomatis) ---
def extract_payee(desc):
    desc_upper = str(desc).upper()
    match_pt = re.search(r'\b(PT|CV)\.?\s+([A-Z0-9\s]+)', desc_upper)
    if match_pt:
        return match_pt.group(0).split('  ')[0] 

    match_ke = re.search(r'(?:KE|DARI|FROM)\s+([A-Z0-9\s]+)', desc_upper)
    if match_ke:
        return match_ke.group(1).strip()[:30]
        
    return ""

# --- PARSER BRI (Format International) ---
def parse_bri(pdf):
    data = []
    for page in pdf.pages:
        table = page.extract_table(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"})
        if not table: continue
        for row in table:
            if len(row) >= 6 and row[0] and re.search(r'\d{2}/\d{2}/\d{2}', str(row[0])):
                deb_txt = str(row[3]).strip() if row[3] else ""
                kre_txt = str(row[4]).strip() if row[4] else ""
                is_debet = deb_txt not in ["", "0.00", "0", "0.0"]
                nominal_raw = deb_txt if is_debet else kre_txt
                
                data.append({
                    "Tanggal": str(row[0]).split(' ')[0].replace('/01/', '/01/20'), 
                    "Keterangan": str(row[1]).replace('\n', ' '),
                    "Nominal": parse_number(nominal_raw, is_indo_format=False), # False = Intl
                    "Jenis": "DB" if is_debet else "CR"
                })
    return pd.DataFrame(data)

# --- PARSER PANIN (Format Indonesia) ---
def parse_panin(pdf):
    data = []
    current_trx = None
    date_regex = re.compile(r'(\d{1,2}-[a-zA-Z]{3}-\d{4})')
    saldo_terakhir = None
    
    for page in pdf.pages:
        text = page.extract_text()
        if not text: continue
        for line in text.split('\n'):
            if "SALDO" in line.upper():
                # Tangkap pola angka Indo (contoh: 1.500.000,00)
                amounts = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})', line)
                if amounts and any(x in line.upper() for x in ["AWAL", "LALU", "PINDAH"]):
                    saldo_terakhir = parse_number(amounts[-1], is_indo_format=True) # True = Indo
            
            match = date_regex.search(line)
            if match:
                if current_trx: data.append(current_trx)
                
                amounts = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})', line)
                if len(amounts) >= 2:
                    nominal_txt, saldo_txt = amounts[0], amounts[-1]
                elif len(amounts) == 1:
                    nominal_txt, saldo_txt = amounts[0], amounts[0]
                else:
                    nominal_txt, saldo_txt = "0,00", "0,00"
                    
                nominal_float = parse_number(nominal_txt, is_indo_format=True)
                saldo_float = parse_number(saldo_txt, is_indo_format=True)
                
                jenis = "CR"
                if saldo_terakhir is not None:
                    if abs(saldo_terakhir - nominal_float - saldo_float) < 1.0:
                        jenis = "DB"
                    elif abs(saldo_terakhir + nominal_float - saldo_float) < 1.0:
                        jenis = "CR"
                    else:
                        if any(k in line.upper() for k in ["RTGS KE", "SETPAJAK", "TARIK", "BIAYA"]):
                            jenis = "DB"
                else:
                    if any(k in line.upper() for k in ["RTGS KE", "SETPAJAK", "TARIK", "BIAYA", "TRF KE"]):
                        jenis = "DB"
                
                saldo_terakhir = saldo_float
                raw_desc = line.replace(match.group(1), "")
                clean_desc = re.sub(r'\d{1,3}(?:\.\d{3})*,\d{2}', '', raw_desc).strip()
                
                current_trx = {
                    "Tanggal": match.group(1).replace('-', '/'),
                    "Keterangan": clean_desc,
                    "Nominal": nominal_float,
                    "Jenis": jenis
                }
            elif current_trx and not any(x in line for x in ["Halaman", "Saldo", "Mata", "Tgl. Transaksi"]):
                clean_line = re.sub(r'\d{1,3}(?:\.\d{3})*,\d{2}', '', line).strip()
                if clean_line:
                    current_trx["Keterangan"] += " " + clean_line
                
    if current_trx: data.append(current_trx)
    return pd.DataFrame(data)

# --- PARSER BCA/MANDIRI (Format International) ---
def parse_generic(pdf, year):
    data = []
    current_trx = None
    date_ptrn = re.compile(r'^(\d{2}/\d{2})\s')
    # Tangkap pola angka Intl (contoh: 14,530,000.00)
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
                    "Nominal": parse_number(nominal_txt, is_indo_format=False), # False = Intl (PERBAIKAN DISINI)
                    "Jenis": "DB" if "DB" in line.upper() else "CR"
                }
            elif current_trx: current_trx["Keterangan"] += " " + line.strip()
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
            st.success(f"✅ Berhasil! {len(df)} transaksi.")
            
            csv_data = []
            for index, row in df.iterrows():
                amount = row['Nominal']
                if row['Jenis'] == 'DB':
                    amount = -abs(amount)
                
                detected_payee = extract_payee(row['Keterangan'])
                
                csv_data.append({
                    "*Date": row['Tanggal'],
                    "*Amount": amount,  # Angka asli (Float), paling aman untuk import CSV ke sistem akunting
                    "Payee": detected_payee,
                    "Description": row['Keterangan'],
                    "Reference": "",     
                    "Check Number": ""   
                })
            
            df_final = pd.DataFrame(csv_data)
            
            # Tampilkan preview di layar dengan format Intl (Koma pemisah ribuan)
            st.dataframe(df_final.style.format({"*Amount": "{:,.2f}"}))
            
            # --- DOWNLOAD BUTTON ---
            # Export CSV dengan angka raw (e.g. 1509600000.00). Ini adalah standar baku Xero/Quickbooks.
            csv_string = df_final.to_csv(index=False, float_format='%.2f').encode('utf-8')
            
            st.download_button(
                label="📥 Download CSV",
                data=csv_string,
                file_name=f"import_{bank_type.lower()}.csv",
                mime="text/csv"
            )
        else:
            st.warning("⚠️ Data kosong. Cek pilihan Bank.")
            
    except Exception as e:
        st.error(f"Error: {e}")

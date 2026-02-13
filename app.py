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
    
    # Deteksi jika angka negatif (Berupa minus di depan atau dikurung kurung)
    is_negative = False
    if clean.startswith('-') or (clean.startswith('(') and clean.endswith(')')):
        is_negative = True
        
    # Bersihkan karakter kurung dan minus sebelum dikonversi
    clean = clean.replace('(', '').replace(')', '').replace('-', '')
    
    if is_indo_format:
        clean = clean.replace('.', '').replace(',', '.')
    else:
        clean = clean.replace(',', '')
        
    try:
        val = float(clean)
        return -val if is_negative else val
    except:
        return 0.0

# --- PARSER BRI ---
def parse_bri(pdf):
    data = []
    current_trx = None
    regex_main = re.compile(r'^(\d{2}/\d{2}/\d{2,4})\s+(?:\d{2}:\d{2}:\d{2}\s+)?(.*)\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})$')
    
    for page in pdf.pages:
        text = page.extract_text()
        if not text: continue
        
        for line in text.split('\n'):
            line = line.strip()
            if not line: continue
            
            match = regex_main.match(line)
            if match:
                if current_trx: data.append(current_trx)
                
                raw_date = match.group(1)
                parts = raw_date.split('/')
                if len(parts) == 3 and len(parts[2]) == 2:
                    tanggal = f"{parts[0]}/{parts[1]}/20{parts[2]}"
                else:
                    tanggal = raw_date
                
                desc_raw = match.group(2).strip()
                deb_txt = match.group(3)
                kre_txt = match.group(4)
                
                deb_val = parse_number(deb_txt, is_indo_format=False)
                kre_val = parse_number(kre_txt, is_indo_format=False)
                
                is_debet = abs(deb_val) > 0
                nominal = deb_val if is_debet else kre_val
                jenis = "DB" if is_debet else "CR"
                
                current_trx = {
                    "Tanggal": tanggal,
                    "Keterangan": desc_raw,
                    "Nominal": nominal,
                    "Jenis": jenis
                }
            elif current_trx:
                if not any(k in line.upper() for k in ["TANGGAL TRANSAKSI", "URAIAN TRANSAKSI", "SALDO", "HALAMAN", "PAGE", "DEBET", "KREDIT"]):
                    current_trx["Keterangan"] += " " + line
                    
    if current_trx: data.append(current_trx)
    return pd.DataFrame(data)

# --- PARSER PANIN ---
def parse_panin(pdf):
    data = []
    current_trx = None
    date_regex = re.compile(r'(\d{1,2}-[a-zA-Z]{3}-\d{4})')
    saldo_terakhir = None
    
    # Update pola untuk menangkap tanda kurung (1.000,00)
    panin_money_ptrn = r'\(?\d{1,3}(?:\.\d{3})*,\d{2}\)?'
    
    for page in pdf.pages:
        text = page.extract_text()
        if not text: continue
        for line in text.split('\n'):
            if "SALDO" in line.upper():
                amounts = re.findall(panin_money_ptrn, line)
                if amounts and any(x in line.upper() for x in ["AWAL", "LALU", "PINDAH"]):
                    saldo_terakhir = parse_number(amounts[-1], is_indo_format=True) 
            
            match = date_regex.search(line)
            if match:
                if current_trx: data.append(current_trx)
                
                amounts = re.findall(panin_money_ptrn, line)
                if len(amounts) >= 2:
                    nominal_txt, saldo_txt = amounts[0], amounts[-1]
                elif len(amounts) == 1:
                    nominal_txt, saldo_txt = amounts[0], amounts[0]
                else:
                    nominal_txt, saldo_txt = "0,00", "0,00"
                    
                # Nominal paksa absolute agar logika math DB/CR berjalan
                nominal_float = abs(parse_number(nominal_txt, is_indo_format=True))
                saldo_float = parse_number(saldo_txt, is_indo_format=True) # Biarkan minus jika ada kurung
                
                jenis = "CR"
                if saldo_terakhir is not None:
                    # Cek Math
                    if abs(saldo_terakhir - nominal_float - saldo_float) < 1.0:
                        jenis = "DB"
                    elif abs(saldo_terakhir + nominal_float - saldo_float) < 1.0:
                        jenis = "CR"
                    else:
                        if any(k in line.upper() for k in ["RTGS KE", "SETPAJAK", "TARIK", "BIAYA", "OD CHG", "ADMIN CHARGE"]):
                            jenis = "DB"
                else:
                    if any(k in line.upper() for k in ["RTGS KE", "SETPAJAK", "TARIK", "BIAYA", "TRF KE", "OD CHG", "ADMIN CHARGE"]):
                        jenis = "DB"
                
                saldo_terakhir = saldo_float
                raw_desc = line.replace(match.group(1), "")
                clean_desc = re.sub(panin_money_ptrn, '', raw_desc).strip()
                
                current_trx = {
                    "Tanggal": match.group(1).replace('-', '/'),
                    "Keterangan": clean_desc,
                    "Nominal": nominal_float,
                    "Jenis": jenis
                }
            elif current_trx and not any(x in line.upper() for x in ["HALAMAN", "SALDO", "MATA", "TGL. TRANSAKSI"]):
                clean_line = re.sub(panin_money_ptrn, '', line).strip()
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
            kata_kunci_blokir = ["SALDO AWAL", "SALDO AKHIR", "SALDO LALU", "RINGKASAN AKUN", "KETERANGAN JUMLAH"]
            
            csv_data = []
            transaksi_valid = 0
            
            for index, row in df.iterrows():
                ket_upper = str(row['Keterangan']).upper()
                is_saldo_summary = any(k in ket_upper for k in kata_kunci_blokir)
                
                if not is_saldo_summary:
                    amount = row['Nominal']
                    if row['Jenis'] == 'DB':
                        amount = -abs(amount)
                    
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

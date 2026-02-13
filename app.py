import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- CONFIG ---
st.set_page_config(page_title="Accounting Converter v8", layout="wide")
st.title("💰 Multi-Bank Converter (Accounting Ready)")
st.markdown("Output angka sudah diformat standard (1,000.00) dan siap dijumlahkan di Excel.")

# --- UI ---
col1, col2 = st.columns(2)
with col1:
    bank_type = st.selectbox("1. Pilih Bank", ["BCA / Mandiri", "BRI", "Panin"])
    uploaded_file = st.file_uploader("2. Upload PDF", type="pdf")
with col2:
    pdf_password = st.text_input("3. Password (Jika ada)", type="password")
    tahun_input = st.text_input("4. Tahun (Hanya BCA/Mandiri)", value="2026")

# --- UTILITY: KONVERSI KE ANGKA MURNI ---
def parse_number(text_val, is_indo_format=True):
    """
    Mengubah teks "1.000.000,00" (Indo) atau "1,000,000.00" (Intl)
    menjadi angka float Python yang valid (1000000.0).
    """
    if not text_val: return 0.0
    
    # Hapus karakter aneh (spasi, newline)
    clean = str(text_val).strip()
    
    if is_indo_format:
        # Format Indo: Hapus titik (ribuan), ganti koma jadi titik (desimal)
        # Contoh: 1.500,50 -> 1500.50
        clean = clean.replace('.', '').replace(',', '.')
    else:
        # Format Intl (BRI): Hapus koma (ribuan)
        # Contoh: 1,500.50 -> 1500.50
        clean = clean.replace(',', '')
        
    try:
        return float(clean)
    except:
        return 0.0

# --- PARSER BRI (Format International: 1,000.00) ---
def parse_bri(pdf):
    data = []
    for page in pdf.pages:
        table = page.extract_table(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"})
        if not table: continue
        for row in table:
            if len(row) >= 6 and row[0] and re.search(r'\d{2}/\d{2}/\d{2}', str(row[0])):
                # Ambil teks mentah
                deb_txt = str(row[3]).strip() if row[3] else ""
                kre_txt = str(row[4]).strip() if row[4] else ""
                
                # Tentukan mana yang ada isinya
                is_debet = deb_txt not in ["", "0.00", "0"]
                nominal_raw = deb_txt if is_debet else kre_txt
                
                # Konversi ke angka (BRI pakai format Intl/False)
                nominal_float = parse_number(nominal_raw, is_indo_format=False)
                
                data.append({
                    "Tanggal": str(row[0]).split(' ')[0].replace('/01/', '/01/20'), 
                    "Keterangan": str(row[1]).replace('\n', ' '),
                    "Cabang": str(row[2]),
                    "Nominal": nominal_float, # Simpan sebagai Angka
                    "Jenis": "DB" if is_debet else "CR",
                    "Saldo": parse_number(row[5], is_indo_format=False)
                })
    return pd.DataFrame(data)

# --- PARSER PANIN (Format Indo: 1.000,00) ---
def parse_panin(pdf):
    data = []
    current_trx = None
    date_regex = re.compile(r'(\d{1,2}-[a-zA-Z]{3}-\d{4})')
    
    for page in pdf.pages:
        text = page.extract_text()
        if not text: continue
        for line in text.split('\n'):
            match = date_regex.search(line)
            if match:
                if current_trx: data.append(current_trx)
                
                # Cari pola angka 1.000,00
                amounts = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', line)
                nominal_txt = amounts[0] if len(amounts) > 0 else "0,00"
                saldo_txt = amounts[-1] if len(amounts) > 1 else "0,00"
                
                # Konversi (Panin pakai format Indo/True)
                nominal_float = parse_number(nominal_txt, is_indo_format=True)
                
                current_trx = {
                    "Tanggal": match.group(1).replace('-', '/'),
                    "Keterangan": line.replace(match.group(1), "").strip(),
                    "Cabang": "0", 
                    "Nominal": nominal_float,
                    "Jenis": "CR", # Default CR, user cek manual jika perlu
                    "Saldo": parse_number(saldo_txt, is_indo_format=True)
                }
            elif current_trx and not any(x in line for x in ["Halaman", "Saldo", "Mata"]):
                current_trx["Keterangan"] += " " + line.strip()
                
    if current_trx: data.append(current_trx)
    return pd.DataFrame(data)

# --- PARSER BCA/MANDIRI (Format Indo: 1.000,00) ---
def parse_generic(pdf, year):
    data = []
    current_trx = None
    date_ptrn = re.compile(r'^(\d{2}/\d{2})\s')
    money_ptrn = re.compile(r'(\d{1,3}(?:,\d{3})*\.\d{2})')
    
    for page in pdf.pages:
        for line in (page.extract_text() or "").split('\n'):
            m = date_ptrn.match(line)
            if m:
                if current_trx: data.append(current_trx)
                moneys = money_ptrn.findall(line)
                
                nominal_txt = moneys[0] if moneys else "0,00"
                saldo_txt = moneys[-1] if len(moneys)>1 else "0,00"
                
                # Konversi (BCA pakai format Indo/True)
                nominal_float = parse_number(nominal_txt, is_indo_format=True)
                
                current_trx = {
                    "Tanggal": f"{m.group(1)}/{year}",
                    "Keterangan": line.strip(), 
                    "Cabang": "0",
                    "Nominal": nominal_float,
                    "Jenis": "DB" if "DB" in line.upper() else "CR",
                    "Saldo": parse_number(saldo_txt, is_indo_format=True)
                }
            elif current_trx: current_trx["Keterangan"] += " " + line.strip()
    if current_trx: data.append(current_trx)
    return pd.DataFrame(data)

# --- EXECUTION ---
if uploaded_file and st.button("🚀 Convert Sekarang"):
    try:
        try:
            pdf = pdfplumber.open(uploaded_file, password=pdf_password if pdf_password else None)
        except:
            st.error("❌ Gagal buka PDF. Cek Password.")
            st.stop()
            
        with st.spinner("Sedang memproses angka..."):
            if bank_type == "BRI": df = parse_bri(pdf)
            elif bank_type == "Panin": df = parse_panin(pdf)
            else: df = parse_generic(pdf, tahun_input)
        pdf.close()
        
        if not df.empty:
            st.success(f"✅ Berhasil! {len(df)} transaksi.")
            
            # Format tampilan di layar (biar ada komanya: 1,000.00)
            st.dataframe(df.style.format({"Nominal": "{:,.2f}", "Saldo": "{:,.2f}"}))
            
            # Download Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            
            st.download_button("📥 Download Excel", buffer.getvalue(), f"hasil_{bank_type.lower()}.xlsx")
        else:
            st.warning("⚠️ Data kosong. Cek pilihan Bank.")
            
    except Exception as e:
        st.error(f"Error: {e}")

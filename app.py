# --- PARSER PANIN ---
def parse_panin(pdf):
    data = []
    current_trx = None
    date_regex = re.compile(r'(\d{1,2}-[a-zA-Z]{3}-\d{4})')
    saldo_terakhir = None
    
    # Fungsi khusus Panin untuk mengubah (123,45) menjadi -123.45
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
            
            # 1. BERHENTI membaca jika sudah masuk area "Ringkasan Akun" (Footer)
            if any(x in line.upper() for x in ["RINGKASAN AKUN", "MUTASI DEBIT", "MUTASI KREDIT"]):
                current_trx = None # Stop gabungkan deskripsi
                continue 
                
            if "SALDO" in line.upper():
                # Regex diubah agar menangkap kurung ()
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
                    
                # Nominal transaksi selalu dibuat positif (absolut), hanya saldo yang boleh minus
                nominal_float = abs(parse_panin_num(nominal_txt))
                saldo_float = parse_panin_num(saldo_txt)
                
                jenis = "CR"
                if saldo_terakhir is not None:
                    # Logika matematika sekarang akan akurat meskipun saldonya minus
                    if abs(saldo_terakhir - nominal_float - saldo_float) < 1.0:
                        jenis = "DB"
                    elif abs(saldo_terakhir + nominal_float - saldo_float) < 1.0:
                        jenis = "CR"
                    else:
                        # Tambahan kata kunci 'CHG' dan 'CHARGE' untuk OD CHG SYS-GEN
                        if any(k in line.upper() for k in ["RTGS", "PAJAK", "TARIK", "BIAYA", "CHG", "CHARGE"]):
                            jenis = "DB"
                else:
                    if any(k in line.upper() for k in ["RTGS", "PAJAK", "TARIK", "BIAYA", "TRF KE", "CHG", "CHARGE"]):
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
                # 2. Filter agar header tabel tidak masuk ke deskripsi
                if not any(x in line.upper() for x in ["HALAMAN", "SALDO", "MATA", "TGL. TRANSAKSI"]):
                    clean_line = re.sub(r'\(?\d{1,3}(?:\.\d{3})*,\d{2}\)?', '', line).strip()
                    if clean_line:
                        current_trx["Keterangan"] += " " + clean_line
                
    if current_trx: data.append(current_trx)
    return pd.DataFrame(data)

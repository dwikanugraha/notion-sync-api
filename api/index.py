import os
import requests
import re
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from dateutil import parser as date_parser

# Inisialisasi aplikasi FastAPI
app = FastAPI()

# --- Model Pydantic untuk validasi request body ---
class LoginCredentials(BaseModel):
    identity: str  # e.g., NPM
    password: str

# --- Variabel Konfigurasi dari Environment Variables ---
# Anda HARUS mengatur ini di Vercel Project Settings -> Environment Variables
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# --- Header untuk Notion API ---
NOTION_HEADERS = {
    "Authorization": f"{NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ==============================================================================
# FUNGSI-FUNGSI HELPER (Diadaptasi dari skrip Anda)
# ==============================================================================

def scrape_jadwal_page(session: requests.Session):
    """Mengekstrak jadwal kuliah dari halaman jadwal."""
    jadwal_url = "https://portal.pknstan.ac.id/stud/jadkul/kulnow"
    try:
        response = session.get(jadwal_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        jadwal_list = []
        table = soup.find('table', class_=['table-striped', 'table-borderless'])
        if not table:
            return []

        rows = table.select('tbody tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 6: continue
            
            # Ekstrak Nama Mata Kuliah
            mk_cell_html = cols[2].decode_contents()
            parts = [part.strip() for part in mk_cell_html.split('<br/>')]
            nama_mk = parts[0].strip() if parts else "Tanpa Nama"
            
            # Membersihkan nama MK dari SKS
            nama_mk_clean = re.sub(r'\s*-\s*\d+\s*sks.*$', '', nama_mk, flags=re.IGNORECASE).strip()

            # --- PERUBAHAN DI SINI ---
            # Menambahkan 'ruangan' ke dalam data yang diambil
            jadwal_list.append({
                'mata_kuliah': nama_mk_clean,
                'ruangan': cols[4].text.strip(), # Mengambil data dari kolom ruangan
                'jadwal_string': cols[3].text.strip(),
            })
            # --- AKHIR PERUBAHAN ---

        return jadwal_list
    except Exception as e:
        print(f"Error saat scrape jadwal: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal mengambil data jadwal: {e}")
    """Mengekstrak jadwal kuliah dari halaman jadwal."""
    jadwal_url = "https://portal.pknstan.ac.id/stud/jadkul/kulnow"
    try:
        response = session.get(jadwal_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        jadwal_list = []
        table = soup.find('table', class_=['table-striped', 'table-borderless'])
        if not table:
            return []

        rows = table.select('tbody tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 6: continue
            
            # Ekstrak Nama Mata Kuliah
            mk_cell_html = cols[2].decode_contents()
            parts = [part.strip() for part in mk_cell_html.split('<br/>')]
            nama_mk = parts[0].strip() if parts else "Tanpa Nama"
            
            # Membersihkan nama MK dari SKS
            nama_mk_clean = re.sub(r'\s*-\s*\d+\s*sks.*$', '', nama_mk, flags=re.IGNORECASE).strip()

            jadwal_list.append({
                'mata_kuliah': nama_mk_clean,
                'jadwal_string': cols[3].text.strip(), # e.g., "Senin, 14 Jul 2025 | 14:00 - 16:30"
            })
        return jadwal_list
    except Exception as e:
        print(f"Error saat scrape jadwal: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal mengambil data jadwal: {e}")

def login_dan_dapatkan_jadwal(identity: str, password: str):
    """Melakukan login dan hanya mengambil data jadwal."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    
    try:
        login_page_url = "https://portal.pknstan.ac.id/auth/masuk"
        session.get(login_page_url, timeout=15)
        
        login_data = {'identity': identity, 'password': password}
        session.post(login_page_url, data=login_data, allow_redirects=True, timeout=15)
        
        # Verifikasi login dengan langsung mencoba scrape jadwal
        jadwal = scrape_jadwal_page(session)

        # Jika jadwal kosong, mungkin login gagal atau memang tidak ada jadwal
        # Kita bisa verifikasi dengan cek URL, tapi cara ini lebih direct
        if not jadwal and 'auth/masuk' in session.get("https://portal.pknstan.ac.id/stud").url:
             raise HTTPException(status_code=401, detail="Login Gagal. Periksa kembali NPM dan Password Anda.")
        
        return jadwal
            
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Error koneksi ke portal: {e}")
    except HTTPException as e:
        raise e # Re-raise HTTPException dari fungsi scrape atau login
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Terjadi error tidak terduga: {e}")

def post_to_notion(nama_matkul: str, start_time: str, end_time: str):
    """Mengirim satu data jadwal ke Notion API."""
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        raise HTTPException(status_code=500, detail="Konfigurasi Notion API (Key atau Database ID) tidak ditemukan di server.")

    payload = {
      "parent": { "database_id": NOTION_DATABASE_ID },
      "properties": {
        "Nama Mata Kuliah": {
          "title": [{ "text": { "content": nama_matkul } }]
        },
        "Tanggal": {
          "date": {
            "start": start_time, # Format ISO 8601
            "end": end_time,     # Format ISO 8601
            "time_zone": "Asia/Jakarta"
          }
        }
      }
    }
    
    try:
        response = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload)
        response.raise_for_status() # Akan error jika status code 4xx atau 5xx
        return response.json()
    except requests.exceptions.HTTPError as e:
        # Memberikan detail error dari Notion jika ada
        error_details = e.response.json()
        raise HTTPException(status_code=e.response.status_code, detail=f"Error dari Notion API: {error_details.get('message', e.response.text)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengirim data ke Notion: {e}")

# ==============================================================================
# ENDPOINT API UTAMA
# ==============================================================================

@app.post("/api/sync-jadwal")
async def sync_jadwal_ke_notion(credentials: LoginCredentials):
    """
    Endpoint utama untuk login, scrape jadwal, dan push ke Notion.
    """
    jadwal_items = login_dan_dapatkan_jadwal(credentials.identity, credentials.password)
    
    if not jadwal_items:
        return {"message": "Tidak ada jadwal yang ditemukan untuk disinkronkan."}

    hasil_notion = []
    errors = []

    for item in jadwal_items:
        try:
            jadwal_str = item['jadwal_string']

            if '-' not in jadwal_str:
                raise ValueError(f"Format jadwal tidak valid, tidak ada pemisah '-': {jadwal_str}")

            parts = jadwal_str.split('-')
            if len(parts) != 2:
                 raise ValueError(f"Format jadwal tidak valid, format split aneh: {jadwal_str}")

            start_str = parts[0].strip()
            end_str = parts[1].strip()

            start_dt = date_parser.parse(start_str)
            end_dt = date_parser.parse(end_str, default=start_dt)
            
            start_iso = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
            end_iso = end_dt.strftime('%Y-%m-%dT%H:%M:%S')

            # --- PERUBAHAN DI SINI ---
            # Menggabungkan nama mata kuliah dan ruangan
            nama_lengkap = f"{item['mata_kuliah']} - {item['ruangan']}"
            # --- AKHIR PERUBAHAN ---

            result = post_to_notion(
                nama_matkul=nama_lengkap, # Menggunakan nama yang sudah digabung
                start_time=start_iso,
                end_time=end_iso
            )
            hasil_notion.append({"status": "sukses", "mata_kuliah": nama_lengkap, "notion_page_id": result.get('id')})
        
        except Exception as e:
            error_detail = e.detail if isinstance(e, HTTPException) else str(e)
            errors.append({"status": "gagal", "mata_kuliah": item.get('mata_kuliah'), "error": error_detail})

    return {
        "message": f"Proses sinkronisasi selesai. Sukses: {len(hasil_notion)}, Gagal: {len(errors)}",
        "sukses": hasil_notion,
        "gagal": errors
    }
    """
    Endpoint utama untuk login, scrape jadwal, dan push ke Notion.
    """
    # Langkah 1: Login dan ambil data jadwal
    jadwal_items = login_dan_dapatkan_jadwal(credentials.identity, credentials.password)
    
    if not jadwal_items:
        return {"message": "Tidak ada jadwal yang ditemukan untuk disinkronkan."}

    hasil_notion = []
    errors = []

    # Langkah 2: Iterasi setiap jadwal dan kirim ke Notion
    for item in jadwal_items:
        try:
            jadwal_str = item['jadwal_string']

            # ==================================================================
            # --- PERUBAHAN LOGIKA PARSING ---
            #
            # Logika ini dirancang untuk format "DD Mmm YYYY HH:MM - HH:MM"
            #
            if '-' not in jadwal_str:
                raise ValueError(f"Format jadwal tidak valid, tidak ada pemisah '-': {jadwal_str}")

            parts = jadwal_str.split('-')
            if len(parts) != 2:
                 raise ValueError(f"Format jadwal tidak valid, format split aneh: {jadwal_str}")

            start_str = parts[0].strip()
            end_str = parts[1].strip()

            # Parsing string awal untuk mendapatkan tanggal dan waktu mulai
            start_dt = date_parser.parse(start_str)

            # Parsing string akhir dengan menggunakan tanggal dari string awal sebagai default
            # Ini akan mengambil '16:30' dan menggabungkannya dengan tanggal dari start_dt
            end_dt = date_parser.parse(end_str, default=start_dt)
            #
            # --- AKHIR PERUBAHAN ---
            # ==================================================================
            
            # Format ke ISO 8601 dengan timezone +07:00 (WIB/Asia/Jakarta)
            start_iso = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
            end_iso = end_dt.strftime('%Y-%m-%dT%H:%M:%S')

            # Langkah 2b: Kirim ke Notion
            result = post_to_notion(
                nama_matkul=item['mata_kuliah'],
                start_time=start_iso,
                end_time=end_iso
            )
            hasil_notion.append({"status": "sukses", "mata_kuliah": item['mata_kuliah'], "notion_page_id": result.get('id')})
        
        except Exception as e:
            # Menangkap error dari parsing atau dari post_to_notion
            error_detail = e.detail if isinstance(e, HTTPException) else str(e)
            errors.append({"status": "gagal", "mata_kuliah": item.get('mata_kuliah'), "error": error_detail})

    return {
        "message": f"Proses sinkronisasi selesai. Sukses: {len(hasil_notion)}, Gagal: {len(errors)}",
        "sukses": hasil_notion,
        "gagal": errors
    }
    """
    Endpoint utama untuk login, scrape jadwal, dan push ke Notion.
    """
    # Langkah 1: Login dan ambil data jadwal
    jadwal_items = login_dan_dapatkan_jadwal(credentials.identity, credentials.password)
    
    if not jadwal_items:
        return {"message": "Tidak ada jadwal yang ditemukan untuk disinkronkan."}

    hasil_notion = []
    errors = []

    # Langkah 2: Iterasi setiap jadwal dan kirim ke Notion
    for item in jadwal_items:
        try:
            jadwal_str = item['jadwal_string']

            # ==================================================================
            # --- PERBAIKAN DIMULAI DI SINI ---
            #
            # Validasi format string jadwal sebelum di-parsing untuk menghindari error.
            # Cek apakah string mengandung pemisah tanggal '|' dan pemisah waktu '-'.
            if '|' not in jadwal_str or '-' not in jadwal_str.split('|')[1]:
                errors.append({
                    "status": "gagal",
                    "mata_kuliah": item.get('mata_kuliah'),
                    "error": f"Format jadwal tidak dikenali atau tidak lengkap: '{jadwal_str}'"
                })
                continue  # Lanjut ke mata kuliah berikutnya
            #
            # --- PERBAIKAN SELESAI ---
            # ==================================================================

            # Langkah 2a: Parsing tanggal dan waktu (sekarang lebih aman)
            parts = jadwal_str.split('|')
            date_part = parts[0].strip()
            time_part = parts[1].strip()
            
            start_time_str, end_time_str = [t.strip() for t in time_part.split('-')]
            
            start_dt = date_parser.parse(f"{date_part} {start_time_str}")
            end_dt = date_parser.parse(f"{date_part} {end_time_str}")
            
            start_iso = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
            end_iso = end_dt.strftime('%Y-%m-%dT%H:%M:%S')

            # Langkah 2b: Kirim ke Notion
            result = post_to_notion(
                nama_matkul=item['mata_kuliah'],
                start_time=start_iso,
                end_time=end_iso
            )
            hasil_notion.append({"status": "sukses", "mata_kuliah": item['mata_kuliah'], "notion_page_id": result.get('id')})
        
        except Exception as e:
            error_detail = e.detail if isinstance(e, HTTPException) else str(e)
            errors.append({"status": "gagal", "mata_kuliah": item.get('mata_kuliah'), "error": error_detail})

    return {
        "message": f"Proses sinkronisasi selesai. Sukses: {len(hasil_notion)}, Gagal: {len(errors)}",
        "sukses": hasil_notion,
        "gagal": errors
    }
    """
    Endpoint utama untuk login, scrape jadwal, dan push ke Notion.
    """
    # Langkah 1: Login dan ambil data jadwal
    jadwal_items = login_dan_dapatkan_jadwal(credentials.identity, credentials.password)
    
    if not jadwal_items:
        return {"message": "Tidak ada jadwal yang ditemukan untuk disinkronkan."}

    hasil_notion = []
    errors = []

    # Langkah 2: Iterasi setiap jadwal dan kirim ke Notion
    for item in jadwal_items:
        try:
            # Langkah 2a: Parsing tanggal dan waktu
            # Contoh string: "Senin, 14 Jul 2025 | 14:00 - 16:30"
            jadwal_str = item['jadwal_string']
            parts = jadwal_str.split('|')
            date_part = parts[0].strip()
            time_part = parts[1].strip()
            
            start_time_str, end_time_str = [t.strip() for t in time_part.split('-')]
            
            # Menggunakan dateutil.parser untuk mengubah string menjadi objek datetime
            # kemudian format ke ISO 8601 dengan timezone +07:00 (WIB)
            start_dt = date_parser.parse(f"{date_part} {start_time_str}")
            end_dt = date_parser.parse(f"{date_part} {end_time_str}")
            
            start_iso = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
            end_iso = end_dt.strftime('%Y-%m-%dT%H:%M:%S')

            # Langkah 2b: Kirim ke Notion
            result = post_to_notion(
                nama_matkul=item['mata_kuliah'],
                start_time=start_iso,
                end_time=end_iso
            )
            hasil_notion.append({"status": "sukses", "mata_kuliah": item['mata_kuliah'], "notion_page_id": result.get('id')})
        
        except Exception as e:
            # Menangkap error per item agar proses tidak berhenti total
            error_detail = e.detail if isinstance(e, HTTPException) else str(e)
            errors.append({"status": "gagal", "mata_kuliah": item.get('mata_kuliah'), "error": error_detail})

    return {
        "message": f"Proses sinkronisasi selesai. Sukses: {len(hasil_notion)}, Gagal: {len(errors)}",
        "sukses": hasil_notion,
        "gagal": errors
    }

# Endpoint root untuk verifikasi bahwa API berjalan
@app.get("/")
def read_root():
    return {"status": "API Jadwal ke Notion sedang berjalan."}
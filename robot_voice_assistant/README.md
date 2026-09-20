# Aegis — دستیار صوتی رباتیک

یک رابط کاملاً صوتی با ربات متحرک برای مکالمه با مدل **GPT-5.6** از GapGPT. کلید API فقط روی سرور نگه‌داری می‌شود؛ مرورگر هرگز آن را دریافت نمی‌کند.

## اجرا

```bash
cd robot_voice_assistant
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# مقدار GAPGPT_API_KEY را در .env وارد کنید.
uvicorn app.main:app --reload
```

سپس `http://127.0.0.1:8000` را با Chrome یا Edge باز کنید. با دکمهٔ مرکزی یا کلید Space صحبت کنید. تشخیص گفتار از Web Speech API مرورگر استفاده می‌کند و ممکن است در Firefox در دسترس نباشد.

## پیکربندی GapGPT

- `GAPGPT_API_KEY`: کلید API GapGPT.
- `GAPGPT_BASE_URL`: نشانی سازگار با OpenAI در حساب GapGPT (پیش‌فرض را با داشبورد خود بررسی کنید).
- `GAPGPT_MODEL`: نام مدل؛ پیش‌فرض `gpt-5.6` است.
- `TAVILY_API_KEY` (اختیاری): برای حالت «تحقیق وب». بدون آن، دستیار همچنان پاسخ می‌دهد اما ادعای جستجوی تازه نمی‌کند.

> برای انتشار عمومی، HTTPS الزامی است؛ مرورگرها دسترسی میکروفن را روی زمینهٔ ناامن مسدود می‌کنند.

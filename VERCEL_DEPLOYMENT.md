# Vercel Frontend Deployment

## Automatisches Deployment (Empfohlen)

1. **Vercel Account verbinden**
   - Gehe zu [vercel.com](https://vercel.com)
   - Login mit GitHub
   - "Add New Project" → Repository auswählen

2. **Projekt konfigurieren**
   - **Framework Preset**: Next.js
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build`
   - **Output Directory**: `.next`
   - **Install Command**: `npm install`

3. **Environment Variables setzen**
   - Gehe zu Project Settings → Environment Variables
   - Füge hinzu:
     ```
     NEXT_PUBLIC_API_URL=https://simplecomptool-production.up.railway.app
     ```
   - Wähle "Production, Preview, and Development"

4. **Deploy**
   - Klicke "Deploy"
   - Vercel baut und deployed automatisch

## Manuelles Deployment via CLI

```bash
# Vercel CLI installieren
npm i -g vercel

# Login
vercel login

# Im frontend Verzeichnis
cd frontend

# Deployment
vercel --prod

# Environment Variable setzen (falls noch nicht in Dashboard)
vercel env add NEXT_PUBLIC_API_URL production
# Dann eingeben: https://simplecomptool-production.up.railway.app
```

## CORS Configuration

⚠️ **WICHTIG**: Nach dem ersten Deployment musst du die Vercel-URL im Backend erlauben.

1. Notiere deine Vercel-URL (z.B. `https://yourapp.vercel.app`)
2. Setze auf Railway die Environment Variable:
   ```bash
   railway variables --set CORS_ORIGINS=https://yourapp.vercel.app,http://localhost:3000
   ```

## Post-Deployment Checks

✅ Teste das Frontend unter deiner Vercel-URL
✅ Öffne Browser DevTools → Network Tab
✅ Versuche einen Scan → sollte keine CORS-Fehler geben
✅ Prüfe dass API-Calls an Railway Backend gehen

## Troubleshooting

### CORS Fehler
- Vercel-URL in Railway CORS_ORIGINS hinzufügen
- Format: `https://yourapp.vercel.app` (ohne trailing slash)

### Build Fehler
- Prüfe ob `NEXT_PUBLIC_API_URL` gesetzt ist
- Logs in Vercel Dashboard → Deployments → Build Logs

### 404 Fehler
- Prüfe ob Root Directory auf `frontend` gesetzt ist
- Output Directory muss `.next` sein

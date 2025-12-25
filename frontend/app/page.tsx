"use client";

import { useState, useEffect } from 'react';

// API-Base-URL aus Environment-Variable
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface PageInfo {
  id: string;
  url: string;
  status: number;
  sha256_text: string;
  title?: string;
  meta_description?: string;
  text_preview?: string;
  raw_download_url?: string;
  text_download_url?: string;
}

interface ErrorDetail {
  code: string;
  message: string;
}

interface ScanResult {
  ok: boolean;
  competitor_id?: string;
  snapshot_id?: string;
  pages?: PageInfo[];
  profile?: string;
  error?: ErrorDetail;
}

interface SnapshotDetails {
  id: string;
  competitor_id: string;
  created_at: string;
  page_count: number;
  notes?: string;
  pages?: PageInfo[];
}

interface Competitor {
  id: string;
  name?: string;
  url: string;
  created_at: string;
  snapshots?: Array<{
    id: string;
    url: string;
    created_at: string;
  }>;
}

export default function Home() {
  const [url, setUrl] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [snapshotDetails, setSnapshotDetails] = useState<SnapshotDetails | null>(null);
  const [error, setError] = useState('');
  const [competitors, setCompetitors] = useState<Competitor[]>([]);

  // Lade alle Competitors beim ersten Laden
  useEffect(() => {
    loadCompetitors();
  }, []);

  const loadCompetitors = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/competitors`);
      if (response.ok) {
        const data = await response.json();
        setCompetitors(data);
      }
    } catch (err) {
      console.error('Fehler beim Laden der Competitors:', err);
    }
  };

  const normalizeUrl = (input: string): string => {
    const trimmed = input.trim();
    if (!trimmed) return trimmed;
    
    // Wenn bereits ein Protokoll vorhanden ist, zurückgeben
    if (trimmed.match(/^https?:\/\//i)) {
      return trimmed;
    }
    
    // Ansonsten "https://" voranstellen
    return `https://${trimmed}`;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    setScanResult(null);
    setSnapshotDetails(null);

    const normalizedUrl = normalizeUrl(url);

    try {
      const response = await fetch(`${API_BASE_URL}/api/scan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: null,
          url: normalizedUrl,
          llm: false, // Für jetzt ohne LLM
        }),
      });

      const result: ScanResult = await response.json();
      
      if (!result.ok) {
        // Fehler vom Backend (strukturiert)
        setScanResult(result);
        if (result.error) {
          setError(`${result.error.code}: ${result.error.message}`);
        } else {
          setError('Scan fehlgeschlagen');
        }
        return;
      }

      setScanResult(result);

      // Snapshot-Details laden, wenn verfügbar
      if (result.snapshot_id) {
        await loadSnapshotDetails(result.snapshot_id);
      }

      // Competitors neu laden
      await loadCompetitors();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setIsLoading(false);
    }
  };

  const loadSnapshotDetails = async (snapshotId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/snapshots/${snapshotId}`);
      if (response.ok) {
        const details: SnapshotDetails = await response.json();
        setSnapshotDetails(details);
      } else {
        console.error('Fehler beim Laden der Snapshot-Details');
      }
    } catch (err) {
      console.error('Fehler beim Laden der Snapshot-Details:', err);
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('de-DE');
  };

  return (
    <div className="container">
      <h1>Simple CompTool</h1>

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <input
            type="text"
            id="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="z.B. bild.de oder https://www.beispiel.de"
            required
            className="url-input"
          />
        </div>

        <button type="submit" disabled={isLoading}>
          {isLoading ? 'Scanne...' : 'Scan starten'}
        </button>
      </form>

      {error && (
        <div className="error">
          <strong>Fehler:</strong> {error}
        </div>
      )}

      {scanResult && (
        <div className="results">
          <h2>Scan-Ergebnis</h2>
          {scanResult.competitor_id && (
            <div className="result-item">
              <div className="result-label">Competitor ID:</div>
              <div className="result-value">{scanResult.competitor_id}</div>
            </div>
          )}
          {scanResult.snapshot_id && (
            <div className="result-item">
              <div className="result-label">Snapshot ID:</div>
              <div className="result-value">{scanResult.snapshot_id}</div>
            </div>
          )}
          <div className="result-item">
            <div className="result-label">Seiten gefunden:</div>
            <div className="result-value">{scanResult.pages?.length ?? 0}</div>
          </div>

          {scanResult.profile && (
            <div className="result-item">
              <div className="result-label">LLM-Profil:</div>
              <div className="result-value profile-text">{scanResult.profile}</div>
            </div>
          )}

          {scanResult.error && (
            <div className="result-item error">
              <div className="result-label">Fehler:</div>
              <div className="result-value">
                <strong>{scanResult.error.code}:</strong> {scanResult.error.message}
              </div>
            </div>
          )}
        </div>
      )}

      {snapshotDetails && (
        <div className="snapshot-details">
          <h2>Snapshot-Details</h2>

          <div className="snapshot-info">
            <div className="info-item">
              <strong>Snapshot ID:</strong> {snapshotDetails.id}
            </div>
            <div className="info-item">
              <strong>Erstellt:</strong> {formatDate(snapshotDetails.created_at)}
            </div>
            <div className="info-item">
              <strong>Seiten:</strong> {snapshotDetails.page_count}
            </div>
            {snapshotDetails.notes && (
              <div className="info-item">
                <strong>Notizen:</strong> {snapshotDetails.notes}
              </div>
            )}
          </div>

          <h3>Gefundene Seiten</h3>
          <div className="pages-table">
            <table>
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Status</th>
                  <th>Titel</th>
                  <th>Hash</th>
                  <th>Text-Vorschau</th>
                  <th>Downloads</th>
                </tr>
              </thead>
              <tbody>
                {snapshotDetails.pages && snapshotDetails.pages.length > 0 ? (
                  snapshotDetails.pages.map((page) => (
                    <tr key={page.id}>
                      <td>
                        <a href={page.url} target="_blank" rel="noopener noreferrer">
                          {page.url}
                        </a>
                      </td>
                      <td>
                        <span className={`status ${page.status === 200 ? 'success' : 'error'}`}>
                          {page.status}
                        </span>
                      </td>
                      <td>{page.title || 'Kein Titel'}</td>
                      <td>
                        <code>{page.sha256_text.substring(0, 12)}...</code>
                      </td>
                      <td>
                        <div className="text-preview">
                          {page.text_preview ? (
                            <span>{page.text_preview}...</span>
                          ) : (
                            <span className="no-preview">Kein Text verfügbar</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <div className="download-links">
                          {page.raw_download_url && (
                            <a
                              href={`${API_BASE_URL}${page.raw_download_url}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="download-link"
                            >
                              HTML
                            </a>
                          )}
                          {page.text_download_url && (
                            <a
                              href={`${API_BASE_URL}${page.text_download_url}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="download-link"
                            >
                              TXT
                            </a>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} style={{ textAlign: 'center', padding: '20px', color: '#666' }}>
                      Keine Seiten gefunden
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {competitors.length > 0 && (
        <div className="competitors-list">
          <h2>Gespeicherte Competitors</h2>
          {competitors.map((competitor) => (
            <div key={competitor.id} className="competitor-item">
              <h3>{competitor.name || 'Unbenannt'} ({competitor.url})</h3>
              <div style={{ fontSize: '14px', color: '#666', marginBottom: '10px' }}>
                Erstellt: {formatDate(competitor.created_at)}
              </div>

              <div className="snapshot-list">
                <strong>Snapshots:</strong>
                {competitor.snapshots && competitor.snapshots.length > 0 ? (
                  competitor.snapshots.map((snapshot) => (
                    <div key={snapshot.id} className="snapshot-item">
                      {formatDate(snapshot.created_at)} - {snapshot.url}
                    </div>
                  ))
                ) : (
                  <div className="snapshot-item" style={{ fontStyle: 'italic', color: '#999' }}>
                    Keine Snapshots vorhanden
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

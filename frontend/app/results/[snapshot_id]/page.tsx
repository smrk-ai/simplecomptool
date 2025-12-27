'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Page {
  id: string;
  url: string;
  canonical_url: string;
  changed: boolean;
  status: number;
  title: string;
  via: string;
  text_length: number;
  extraction_version: string;
}

interface Social {
  platform: string;
  url: string;
  handle?: string;
}

interface SnapshotDetails {
  id: string;
  competitor_id: string;
  competitor_name: string;
  competitor_url: string;
  created_at: string;
  status: string;
  pages: Page[];
  profile: string | null;
  socials: Social[];
  stats: {
    total_pages: number;
    changed_pages: number;
    unchanged_pages: number;
  };
}

export default function ResultsPage() {
  const params = useParams();
  const snapshot_id = params.snapshot_id as string;

  const [snapshot, setSnapshot] = useState<SnapshotDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadSnapshot();
  }, [snapshot_id]);

  const loadSnapshot = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/snapshots/${snapshot_id}`);

      if (!response.ok) {
        throw new Error('Snapshot nicht gefunden');
      }

      const data = await response.json();
      setSnapshot(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Fehler beim Laden');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <h2>Lädt Snapshot-Details...</h2>
      </div>
    );
  }

  if (error || !snapshot) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <h2>Fehler: {error}</h2>
        <a href="/">← Zurück zur Startseite</a>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '40px 20px' }}>
      {/* Header */}
      <div style={{ marginBottom: '40px' }}>
        <a href="/" style={{ color: '#666', textDecoration: 'none' }}>← Zurück</a>
        <h1 style={{ marginTop: '20px' }}>{snapshot.competitor_name}</h1>
        <p style={{ color: '#666' }}>
          Gescannt: {new Date(snapshot.created_at).toLocaleString('de-DE')}
        </p>
        <p style={{ color: '#666' }}>
          Status: <strong>{snapshot.status}</strong>
        </p>
      </div>

      {/* Profil */}
      {snapshot.profile && (
        <section style={{ marginBottom: '40px', padding: '20px', background: '#f5f5f5', borderRadius: '8px' }}>
          <h2>Profil</h2>
          <p style={{ lineHeight: '1.6' }}>{snapshot.profile}</p>
        </section>
      )}

      {/* Social Media */}
      {snapshot.socials && snapshot.socials.length > 0 && (
        <section style={{ marginBottom: '40px' }}>
          <h2>Social Media</h2>
          <div style={{ display: 'flex', gap: '15px', flexWrap: 'wrap' }}>
            {snapshot.socials.map((social, idx) => (
              <a
                key={idx}
                href={social.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  padding: '10px 20px',
                  background: '#007bff',
                  color: 'white',
                  textDecoration: 'none',
                  borderRadius: '4px'
                }}
              >
                {social.platform}
                {social.handle && ` (@${social.handle})`}
              </a>
            ))}
          </div>
        </section>
      )}

      {/* Stats */}
      <section style={{ marginBottom: '40px', padding: '20px', background: '#f9f9f9', borderRadius: '8px' }}>
        <h2>Statistik</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
          <div>
            <div style={{ fontSize: '24px', fontWeight: 'bold' }}>{snapshot.stats.total_pages}</div>
            <div style={{ color: '#666' }}>Gesamt</div>
          </div>
          <div>
            <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#28a745' }}>
              {snapshot.stats.changed_pages}
            </div>
            <div style={{ color: '#666' }}>Geändert</div>
          </div>
          <div>
            <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#6c757d' }}>
              {snapshot.stats.unchanged_pages}
            </div>
            <div style={{ color: '#666' }}>Unverändert</div>
          </div>
        </div>
      </section>

      {/* Pages Tabelle */}
      <section>
        <h2>Gescannte Seiten ({snapshot.pages.length})</h2>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '20px' }}>
            <thead>
              <tr style={{ background: '#f5f5f5', borderBottom: '2px solid #ddd' }}>
                <th style={{ padding: '12px', textAlign: 'left' }}>URL</th>
                <th style={{ padding: '12px', textAlign: 'center' }}>Status</th>
                <th style={{ padding: '12px', textAlign: 'center' }}>Geändert</th>
                <th style={{ padding: '12px', textAlign: 'center' }}>Länge</th>
                <th style={{ padding: '12px', textAlign: 'center' }}>Aktionen</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.pages.map((page) => (
                <tr key={page.id} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={{ padding: '12px' }}>
                    <div style={{ fontWeight: 'bold' }}>{page.title || 'Kein Titel'}</div>
                    <div style={{ fontSize: '14px', color: '#666' }}>{page.canonical_url}</div>
                  </td>
                  <td style={{ padding: '12px', textAlign: 'center' }}>
                    <span style={{
                      padding: '4px 8px',
                      background: page.status === 200 ? '#d4edda' : '#f8d7da',
                      color: page.status === 200 ? '#155724' : '#721c24',
                      borderRadius: '4px',
                      fontSize: '14px'
                    }}>
                      {page.status}
                    </span>
                  </td>
                  <td style={{ padding: '12px', textAlign: 'center' }}>
                    {page.changed ? (
                      <span style={{ color: '#28a745' }}>✓ Geändert</span>
                    ) : (
                      <span style={{ color: '#6c757d' }}>- Unverändert</span>
                    )}
                  </td>
                  <td style={{ padding: '12px', textAlign: 'center' }}>
                    {page.text_length.toLocaleString()} chars
                  </td>
                  <td style={{ padding: '12px', textAlign: 'center' }}>
                    <a
                      href={`${API_BASE_URL}/api/pages/${page.id}/raw`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ marginRight: '10px', color: '#007bff' }}
                    >
                      HTML
                    </a>
                    <a
                      href={`${API_BASE_URL}/api/pages/${page.id}/text`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: '#007bff' }}
                    >
                      Text
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

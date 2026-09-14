import React, { useEffect, useMemo, useRef, useState } from 'react';
import AlbumsEndpoints from '../../shared/api/albums';
import ApiClient from '../../shared/api/client';
import './AlbumCanvas.css';

// Freeform mode: drag to move, corner handle to resize, press to bring to
// front. Placement is per membership row and written whole, debounced, so
// arrowing a tile across the board is one request, not sixty.
//
// A tile with no stored placement is dealt a slot in a grid on first render,
// so switching an album to freeform starts from something readable rather
// than a pile in the corner.

const DEFAULT_W = 180;
const MIN_W = 80;
const MAX_W = 900;
const GAP = 16;
const SAVE_MS = 500;

function seed(items, columns = 5) {
  return items.map((it, i) => {
    const p = it.placement || {};
    const has = Number.isFinite(p.x) && Number.isFinite(p.y);
    return {
      id: it.id,
      x: has ? p.x : GAP + (i % columns) * (DEFAULT_W + GAP),
      y: has ? p.y : GAP + Math.floor(i / columns) * (DEFAULT_W * 4 / 3 + GAP + 24),
      w: Number.isFinite(p.w) && p.w >= MIN_W ? p.w : DEFAULT_W,
      z: Number.isFinite(p.z) ? p.z : i + 1,
    };
  });
}

function AlbumCanvas({ albumId, items, onOpen }) {
  const [tiles, setTiles] = useState(() => seed(items));
  const [status, setStatus] = useState('');
  const drag = useRef(null);
  const saveTimer = useRef(null);
  const dirty = useRef(false);
  const byId = useMemo(() => Object.fromEntries(items.map(i => [i.id, i])), [items]);

  // Items added or removed while in freeform: keep existing placements, deal
  // the newcomers a slot, drop the departed.
  useEffect(() => {
    setTiles(prev => {
      const keep = new Map(prev.map(t => [t.id, t]));
      return seed(items).map(t => keep.get(t.id) || t);
    });
  }, [items]);

  const scheduleSave = (next) => {
    dirty.current = true;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      dirty.current = false;
      setStatus('saving');
      const answer = await AlbumsEndpoints.setAlbumLayout(albumId, next.map(t => ({
        favourite_id: t.id, x: Math.round(t.x), y: Math.round(t.y), w: Math.round(t.w), z: t.z,
      })));
      setStatus(answer && answer.ok !== false ? '' : 'not saved');
    }, SAVE_MS);
  };
  useEffect(() => () => clearTimeout(saveTimer.current), []);

  const bump = (id) => (ts) => {
    const top = Math.max(0, ...ts.map(t => t.z)) + 1;
    return ts.map(t => (t.id === id ? { ...t, z: top } : t));
  };

  const onPointerDown = (e, id, mode) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const t = tiles.find(x => x.id === id);
    drag.current = { id, mode, startX: e.clientX, startY: e.clientY, ox: t.x, oy: t.y, ow: t.w, moved: false };
    setTiles(bump(id));
  };

  const onPointerMove = (e) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    setTiles(ts => ts.map(t => {
      if (t.id !== d.id) return t;
      if (d.mode === 'resize') {
        return { ...t, w: Math.max(MIN_W, Math.min(MAX_W, d.ow + dx)) };
      }
      return { ...t, x: Math.max(0, d.ox + dx), y: Math.max(0, d.oy + dy) };
    }));
  };

  const onPointerUp = () => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    setTiles(ts => { scheduleSave(ts); return ts; });
  };

  const onDoubleClick = (id) => {
    const item = byId[id];
    if (item && onOpen) onOpen(item);
  };

  const height = Math.max(400, ...tiles.map(t => t.y + t.w * 4 / 3 + 48));

  return (
    <div className="alb-canvas-wrap ar-scroll">
      <div className="alb-canvas" style={{ height }} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
        {tiles.map(t => {
          const item = byId[t.id];
          if (!item) return null;
          const img = item.image_path ? ApiClient.getImageUrl(item.image_path) : '';
          return (
            <div
              key={t.id}
              className="alb-cv-tile"
              style={{ left: t.x, top: t.y, width: t.w, zIndex: t.z }}
              onPointerDown={(e) => onPointerDown(e, t.id, 'move')}
              onDoubleClick={() => onDoubleClick(t.id)}
              title="Drag to move · double-click to open"
            >
              {img
                ? <img src={img} alt={item.collection?.designer || ''} draggable={false} />
                : <span className="alb-cv-blank">{item.kind}</span>}
              <span className="alb-cv-cap">{item.collection?.designer}{item.look?.number ? ` · ${String(item.look.number).padStart(2, '0')}` : ''}</span>
              <span
                className="alb-cv-handle"
                onPointerDown={(e) => { e.stopPropagation(); onPointerDown(e, t.id, 'resize'); }}
                aria-hidden="true"
              />
            </div>
          );
        })}
      </div>
      {status && <span className="alb-cv-status">{status}</span>}
    </div>
  );
}

export default AlbumCanvas;

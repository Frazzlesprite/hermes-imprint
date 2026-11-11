// Imprint - Desktop library.
//
// Loaded uncompiled, so there is no JSX here: every element is a jsx()/jsxs()
// call from react/jsx-runtime. Only @hermes/plugin-sdk, react and
// react/jsx-runtime are imported, and the app's own markup is never reached
// into. The shelf reads the plugin's own backend at /api/plugins/imprint/.

import {
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  STATUSBAR_AREAS,
  PALETTE_AREA,
  host
} from '@hermes/plugin-sdk'
import { useState, useEffect, useCallback } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ROUTE = '/imprint'

const INK = 'var(--ui-text-primary, #141210)'
const PAPER = 'var(--ui-bg-primary, #fbf8f2)'
const MUTED = 'var(--ui-text-tertiary, #6b6459)'
const ACCENT = '#8a2b16'
const RULE = 'rgba(138, 43, 22, 0.18)'

const GENRES = ['epic', 'noir', 'ships-log']

async function rest(ctx, path, options) {
  // ctx.rest is a callable in the SDK; accept the object form too so a
  // version bump cannot silently break the shelf.
  try {
    if (typeof ctx.rest === 'function') return await ctx.rest(path, options)
    if (ctx.rest && typeof ctx.rest.get === 'function') return await ctx.rest.get(path)
    if (ctx.rest && typeof ctx.rest.request === 'function') return await ctx.rest.request(path, options)
  } catch (error) {
    return { ok: false, error: String(error && error.message ? error.message : error) }
  }
  return { ok: false, error: 'no backend route available' }
}

function citeBody(body) {
  // [e123] becomes a superscript span; everything else is plain text.
  const parts = String(body || '').split(/(\[e\d+\])/g)
  return parts.map((part, index) => {
    const match = /^\[(e\d+)\]$/.exec(part)
    if (match) {
      return jsx('sup', {
        style: { color: ACCENT, fontSize: '0.62em', fontFamily: 'ui-monospace, monospace', marginLeft: '1px' },
        children: match[1]
      }, `cite-${index}`)
    }
    return part
  })
}

function coverBlock(book, index) {
  const height = 74 + ((index * 13) % 28)
  return jsxs('button', {
    type: 'button',
    onClick: () => book.onSelect(book.week),
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '4px',
      padding: 0,
      border: 'none',
      background: 'transparent',
      cursor: 'pointer',
      textAlign: 'left'
    }
  }, [
    jsx('div', {
      style: {
        width: '58px',
        height: `${height}px`,
        background: 'linear-gradient(160deg, #f6efe2 0%, #e9dcc8 100%)',
        borderLeft: `3px solid ${ACCENT}`,
        boxShadow: '0 1px 3px rgba(0,0,0,0.18)',
        borderRadius: '2px'
      }
    }, `cover-${book.week}`),
    jsx('div', { style: { fontSize: '10px', color: MUTED }, children: book.week }, `week-${book.week}`)
  ], `shelf-${book.week}`)
}

function ExecutiveRow({ label, value }) {
  return jsxs('div', {
    style: { display: 'grid', gridTemplateColumns: '86px 1fr', gap: '10px', fontSize: '12px', marginBottom: '6px' }
  }, [
    jsx('div', { style: { color: ACCENT, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '10px' }, children: label }, 'l'),
    jsx('div', { style: { color: INK }, children: value }, 'v')
  ])
}

function ChapterPage({ book, chapter, page, pages }) {
  return jsxs('div', {
    style: {
      background: PAPER,
      border: `1px solid ${RULE}`,
      borderRadius: '3px',
      padding: '34px 40px',
      minHeight: '420px',
      boxShadow: '0 2px 10px rgba(0,0,0,0.10)',
      fontFamily: '"Iowan Old Style", Palatino, Georgia, serif'
    }
  }, [
    jsx('div', {
      style: { fontSize: '9px', letterSpacing: '0.16em', color: ACCENT, textTransform: 'uppercase' },
      children: `${chapter.genre || book.genre} - ${book.week}`
    }, 'kicker'),
    jsx('h2', { style: { fontSize: '22px', margin: '10px 0 18px', color: INK }, children: chapter.title }, 'title'),
    jsx('div', { style: { fontSize: '13px', lineHeight: 1.7, color: INK }, children: citeBody(chapter.body_md) }, 'body'),
    jsx('div', {
      style: { marginTop: '24px', fontSize: '10px', color: MUTED, textAlign: 'center' },
      children: `page ${page + 1} of ${pages}`
    }, 'folio')
  ], 'page')
}

function LibraryPage({ ctx }) {
  const [books, setBooks] = useState([])
  const [week, setWeek] = useState(null)
  const [book, setBook] = useState(null)
  const [chapters, setChapters] = useState([])
  const [page, setPage] = useState(0)
  const [genre, setGenre] = useState('epic')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const loadShelf = useCallback(async () => {
    const result = await rest(ctx, '/books')
    if (!result || result.ok === false) {
      setError(result && result.error ? result.error : 'shelf unavailable')
      return
    }
    setError(null)
    setBooks(result.books || [])
    if (result.compile && result.compile.state === 'running') setBusy(true)
    if (!week && result.books && result.books.length) setWeek(result.books[0].week)
  }, [ctx, week])

  useEffect(() => { loadShelf() }, [loadShelf])

  useEffect(() => {
    if (!week) return
    let cancelled = false
    rest(ctx, `/books/${week}`).then(result => {
      if (cancelled) return
      if (!result || result.ok === false) {
        setError(result && result.error ? result.error : 'book unavailable')
        return
      }
      setError(null)
      setBook(result.book)
      setChapters(result.chapters || [])
      setPage(0)
      if (result.book && result.book.genre) setGenre(result.book.genre)
    })
    return () => { cancelled = true }
  }, [ctx, week])

  const compile = useCallback(async () => {
    setBusy(true)
    const result = await rest(ctx, '/compile', { method: 'POST', body: { week, genre } })
    if (!result || result.ok === false) {
      setBusy(false)
      setError(result && result.error ? result.error : 'compile failed to start')
      return
    }
    host.notify({ kind: 'info', message: `Imprint: compiling ${week || 'this week'} as ${genre}.` })
    const timer = setInterval(async () => {
      const shelf = await rest(ctx, '/books')
      if (shelf && shelf.compile && shelf.compile.state !== 'running') {
        clearInterval(timer)
        setBusy(false)
        loadShelf()
      }
    }, 3000)
  }, [ctx, week, genre, loadShelf])

  const burn = useCallback(async () => {
    const result = await rest(ctx, '/burn', { method: 'POST', body: { week } })
    if (result && result.ok === false) setError(result.error || 'burn failed')
    else {
      host.notify({ kind: 'info', message: `Imprint: erased ${week}.` })
      setWeek(null)
      loadShelf()
    }
  }, [ctx, week, loadShelf])

  const chapter = chapters[page] || null
  const totalPages = Math.max(1, chapters.length)

  return jsxs('div', {
    style: { display: 'flex', height: '100%', background: 'var(--ui-bg-secondary, #f4efe6)', overflow: 'hidden' }
  }, [
    // shelf
    jsxs('aside', {
      style: { width: '168px', borderRight: `1px solid ${RULE}`, padding: '14px 12px', overflowY: 'auto' }
    }, [
      jsx('div', {
        style: { fontSize: '10px', letterSpacing: '0.16em', textTransform: 'uppercase', color: ACCENT, marginBottom: '12px' },
        children: 'The shelf'
      }, 'head'),
      books.length === 0
        ? jsx('div', { style: { fontSize: '11px', color: MUTED }, children: 'No weeks compiled yet.' }, 'empty')
        : jsxs('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '10px' } },
            books.map((item, index) => coverBlock({ ...item, onSelect: setWeek }, index)), 'covers')
    ], 'shelf'),

    // book
    jsxs('main', { style: { flex: 1, padding: '18px 22px', overflowY: 'auto' } }, [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px', flexWrap: 'wrap' }
      }, [
        jsx('div', { style: { fontSize: '13px', fontWeight: 600, color: INK }, children: 'Imprint' }, 'name'),
        jsx('select', {
          value: genre,
          onChange: event => setGenre(event.target.value),
          style: { fontSize: '11px', padding: '3px 6px', border: `1px solid ${RULE}`, borderRadius: '3px', background: PAPER, color: INK },
          children: GENRES.map(option => jsx('option', { value: option, children: option }, option))
        }, 'genre'),
        jsx('button', {
          type: 'button',
          onClick: compile,
          disabled: busy,
          style: { fontSize: '11px', padding: '4px 10px', border: `1px solid ${ACCENT}`, color: ACCENT, background: 'transparent', borderRadius: '3px', cursor: busy ? 'default' : 'pointer' },
          children: busy ? 'compiling...' : 'Compile this week'
        }, 'compile'),
        jsx('button', {
          type: 'button',
          onClick: burn,
          disabled: !week,
          style: { fontSize: '11px', padding: '4px 10px', border: `1px solid ${RULE}`, color: MUTED, background: 'transparent', borderRadius: '3px', cursor: 'pointer' },
          children: 'Burn'
        }, 'burn')
      ], 'bar'),

      error ? jsx('div', {
        style: { fontSize: '11px', color: ACCENT, marginBottom: '10px' },
        children: error
      }, 'error') : null,

      book ? jsxs('div', {
        style: { display: 'grid', gridTemplateColumns: '1fr 240px', gap: '18px', alignItems: 'start' }
      }, [
        chapter
          ? jsx(ChapterPage, { book, chapter, page, pages: totalPages }, 'chapter')
          : jsx('div', { style: { fontSize: '12px', color: MUTED }, children: 'This book has no chapters.' }, 'nochapter'),
        jsxs('div', {}, [
          jsx('div', {
            style: { display: 'flex', gap: '8px', marginBottom: '14px' }
          }, [
            jsx('button', {
              type: 'button',
              onClick: () => setPage(Math.max(0, page - 1)),
              disabled: page === 0,
              style: { flex: 1, fontSize: '12px', padding: '5px', border: `1px solid ${RULE}`, borderRadius: '3px', background: 'transparent', color: INK, cursor: 'pointer' },
              children: '◀'
            }, 'prev'),
            jsx('button', {
              type: 'button',
              onClick: () => setPage(Math.min(totalPages - 1, page + 1)),
              disabled: page >= totalPages - 1,
              style: { flex: 1, fontSize: '12px', padding: '5px', border: `1px solid ${RULE}`, borderRadius: '3px', background: 'transparent', color: INK, cursor: 'pointer' },
              children: '▶'
            }, 'next')
          ], 'turn'),
          jsxs('div', {
            style: { border: `1px solid ${RULE}`, borderRadius: '3px', padding: '12px', background: PAPER }
          }, [
            jsx('div', { style: { fontSize: '10px', letterSpacing: '0.1em', textTransform: 'uppercase', color: ACCENT, marginBottom: '8px' }, children: 'Executive edition' }, 'exec-head'),
            jsx(ExecutiveRow, { label: 'Verified', value: `${book.sentences_verified} / ${book.sentences_total}` }, 'verified'),
            jsx(ExecutiveRow, { label: 'Chapters', value: String(chapters.length) }, 'chapters'),
            jsx(ExecutiveRow, { label: 'Compiled', value: String(book.compiled_at || '').slice(0, 16).replace('T', ' ') }, 'compiled')
          ], 'exec'),
          jsx('div', {
            style: { marginTop: '12px', fontSize: '10px', color: MUTED, lineHeight: 1.6 },
            children: 'Every sentence cites the event it came from. The appendix lists every cited event.'
          }, 'note')
        ], 'side')
      ], 'book') : jsx('div', {
        style: { fontSize: '12px', color: MUTED },
        children: busy ? 'Compiling the week...' : 'Pick a week, or compile the current one.'
      }, 'placeholder')
    ], 'main')
  ], 'root')
}

function StatusChip({ ctx }) {
  const [count, setCount] = useState(null)

  useEffect(() => {
    let cancelled = false
    rest(ctx, '/books').then(result => {
      if (cancelled || !result || result.ok === false) return
      setCount((result.books || []).length)
    })
    return () => { cancelled = true }
  }, [ctx])

  return jsx('button', {
    type: 'button',
    onClick: () => host.navigate(ROUTE),
    style: { padding: '0 6px', fontSize: '11px', color: MUTED, background: 'transparent', border: 'none', cursor: 'pointer' },
    children: count === null ? 'imprint' : `imprint - ${count}`
  })
}

export default {
  id: 'imprint',
  name: 'Imprint',
  register(ctx) {
    ctx.registerMany([
      {
        id: 'library',
        area: ROUTES_AREA,
        data: { path: ROUTE },
        render: () => jsx(LibraryPage, { ctx })
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: ROUTE, label: 'Imprint', codicon: 'book' }
      },
      {
        id: 'chip',
        area: STATUSBAR_AREAS.right,
        order: 140,
        render: () => jsx(StatusChip, { ctx })
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'imprint.open',
          label: 'Imprint: open the library',
          keywords: ['imprint', 'book', 'library', 'week'],
          run: () => host.navigate(ROUTE)
        }
      },
      {
        id: 'compile',
        area: PALETTE_AREA,
        data: {
          id: 'imprint.compile',
          label: 'Imprint: compile this week',
          keywords: ['imprint', 'compile', 'book', 'report'],
          run: async () => {
            const result = await rest(ctx, '/compile', { method: 'POST', body: {} })
            host.notify({
              kind: result && result.ok === false ? 'error' : 'info',
              message: result && result.ok === false
                ? `Imprint: ${result.error}`
                : 'Imprint: compiling this week.'
            })
          }
        }
      },
      {
        id: 'genre',
        area: PALETTE_AREA,
        data: {
          id: 'imprint.genre',
          label: 'Imprint: switch genre',
          keywords: ['imprint', 'genre', 'voice', 'epic', 'noir'],
          run: () => host.navigate(ROUTE)
        }
      }
    ])
  }
}

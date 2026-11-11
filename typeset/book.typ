// Imprint - book template.
//
// A5, one column, ruled like a working notebook. The number that matters -
// the verification ratio - is set large wherever it appears, because it is
// the claim the book is making.

#let data = json("book.json")
#let acc = rgb("#8a2b16")
#let ink = rgb("#141210")
#let faint = rgb("#6b6459")
#let rule = rgb("#d8d0c2")
#let paper = rgb("#f7f3ea")
#let ghost = rgb("#e7decf")

#let mono = ("Cascadia Mono", "Consolas", "Courier New")
#let serif = ("Georgia", "Times New Roman")

#let chapter-head = state("chapter-head", "")

#set page(
  paper: "a5",
  margin: (x: 14mm, top: 15mm, bottom: 16mm),
  numbering: none,
  fill: paper,
  header: context {
    set text(font: serif, size: 6.4pt, fill: luma(125), tracking: 0.9pt)
    block(width: 100%)[
      #grid(
        columns: (1fr, 1fr),
        upper(chapter-head.get()),
        align(right)[#upper(data.week)],
      )
      #v(1.2mm)
      #line(length: 100%, stroke: (thickness: 0.4pt, paint: rule))
    ]
  },
  footer: context {
    let p = counter(page).get().first()
    set text(font: serif, size: 7.5pt, fill: luma(120))
    if calc.odd(p) { align(right)[#p] } else { align(left)[#p] }
  },
)

#set text(font: serif, size: 9.4pt, fill: ink, lang: "en")
#set par(justify: true, leading: 0.62em)
#set heading(numbering: none)

#let ordinals = ("One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
  "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen")
#let ordinal(n) = ordinals.at(calc.min(calc.max(n, 1), 15) - 1)

#let cite-label(ids) = {
  let nums = ids.map(i => int(i.slice(1))).sorted()
  let parts = ()
  let start = none
  let prev = none
  for n in nums {
    if start == none { start = n; prev = n; continue }
    if n == prev + 1 { prev = n; continue }
    parts.push(if start == prev { "e" + str(start) } else { "e" + str(start) + "-e" + str(prev) })
    start = n
    prev = n
  }
  if start != none {
    parts.push(if start == prev { "e" + str(start) } else { "e" + str(start) + "-e" + str(prev) })
  }
  parts.join(", ")
}

// ---------------------------------------------------------------- cover
#page(header: none, footer: none, numbering: none)[
  #let peak = data.chapters.map(c => c.stakes).fold(-1, calc.max)

  #place(top + right, dx: -4mm, dy: 2mm)[
    #text(size: 118pt, fill: ghost)[#str(data.edition)]
  ]

  #place(top + left, dx: 0mm, dy: 2mm)[
    #text(size: 7pt, tracking: 2pt, fill: acc)[#upper[2026 - week #str(data.edition)]]
  ]

  #place(top + left, dx: 0mm, dy: 54mm, block(width: 112mm)[
    #text(size: 38pt)[#data.title]
    #v(4mm)
    #line(length: 34mm, stroke: (thickness: 1.4pt, paint: acc))
  ])

  // one tick per chapter; the chapter that cost the most stands taller
  #place(top + left, dx: 0mm, dy: 118mm)[
    #for c in data.chapters [
      #box(
        width: 2.2mm,
        height: if c.stakes == peak { 10mm } else { 5mm },
        fill: if c.stakes == peak { acc } else if c.label == "the dead end" { ghost } else { ink },
        inset: 0pt,
      )
      #h(1.5mm)
    ]
  ]

  #place(bottom + left, dy: -14mm, block(width: 120mm)[
    #line(length: 120mm, stroke: (thickness: 0.4pt, paint: rule))
    #v(3mm)
    #grid(
      columns: (1fr, 1fr),
      text(size: 7pt, tracking: 1.4pt)[#upper[#data.genre_label edition]],
      align(right)[#text(size: 7pt, fill: faint)[#data.range]],
    )
    #v(1.5mm)
    #text(size: 7pt, fill: faint)[
      #str(data.colophon.chapters) chapters, #str(data.colophon.events) events, each citing what it came from.
    ]
  ])
]

// ------------------------------------------------------------- colophon
#chapter-head.update(data.title)
#pagebreak()
#v(6mm)
#text(size: 6.8pt, tracking: 2pt, fill: acc)[#upper[Colophon]]

#v(6mm)
#grid(
  columns: (auto, 1fr),
  column-gutter: 6mm,
  align(bottom)[
    #text(size: 34pt)[#str(data.colophon.verified)]
    #text(size: 16pt, fill: faint)[#(" / " + str(data.colophon.sentences))]
  ],
  align(bottom)[
    #text(size: 8.4pt)[sentences carry a verified citation.]
    #linebreak()
    #text(size: 8.4pt, fill: faint)[#(
      if data.colophon.cut == 0 { "nothing was cut." }
      else { str(data.colophon.cut) + " were cut." }
    )]
  ],
)

#v(4mm)
#line(length: 100%, stroke: (thickness: 0.4pt, paint: rule))
#v(4mm)

#text(size: 8pt, fill: faint)[
  #str(data.colophon.events) events - #str(data.colophon.quests) quests -
  #str(data.colophon.chapters) chapters - build #data.colophon.build_hash
]
#v(2mm)
#text(size: 8pt, fill: faint)[#data.colophon.mode_text]
#v(2mm)
#text(size: 8pt, fill: faint)[#data.colophon.privacy]

// ------------------------------------------------------------ executive
#chapter-head.update(data.title)
#pagebreak()
#text(size: 6.8pt, tracking: 2pt, fill: acc)[#upper[Executive edition]]
#v(3mm)
#text(size: 15pt)[The week in one page]
#v(2mm)
#line(length: 100%, stroke: (thickness: 1pt, paint: acc))
#v(7mm)

#let big(n, label) = block[
  #text(size: 28pt)[#n]
  #linebreak()
  #text(size: 6.4pt, tracking: 1.1pt, fill: faint)[#upper[#label]]
]

#grid(
  columns: (1fr, 1fr, 1fr, 1fr),
  column-gutter: 4mm,
  big(str(data.exec.shipped.len()), "Shipped"),
  big(str(data.exec.blocked.len()), "Blocked"),
  big(str(data.exec.owed.len()), "Owed"),
  big("$" + str(calc.round(data.exec.spend_usd * 100) / 100), "Spend"),
)

#v(4mm)
#line(length: 100%, stroke: (thickness: 0.4pt, paint: rule))
#v(5mm)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 8mm,
  [
    #text(size: 6.4pt, tracking: 1.1pt, fill: acc)[#upper[Shipped]]
    #v(2mm)
    #for item in data.exec.shipped [ #item #linebreak() ]
    #if data.exec.shipped.len() == 0 { text(fill: faint)[nothing] }
  ],
  [
    #text(size: 6.4pt, tracking: 1.1pt, fill: acc)[#upper[Blocked and owed]]
    #v(2mm)
    #for item in data.exec.blocked [ #item #linebreak() ]
    #for item in data.exec.owed [ #item #linebreak() ]
    #if data.exec.blocked.len() + data.exec.owed.len() == 0 { text(fill: faint)[nothing] }
  ],
)

#v(10mm)
#line(length: 100%, stroke: (thickness: 0.4pt, paint: rule))
#v(3mm)
#grid(
  columns: (1fr, 1fr, 1fr),
  text(size: 8pt, fill: faint)[#str(data.exec.hours) hours],
  align(center)[#text(size: 8pt, fill: faint)[#str(data.exec.events) events - #str(data.exec.quests) quests]],
  align(right)[#text(size: 8pt, fill: faint)[#str(data.colophon.verified) of #str(data.colophon.sentences) cited]],
)

// -------------------------------------------------------------- contents
#chapter-head.update(data.title)
#pagebreak()
#text(size: 6.8pt, tracking: 2pt, fill: acc)[#upper[Contents]]
#v(5mm)

#for c in data.chapters [
  #grid(
    columns: (7mm, 1fr, auto),
    text(size: 8pt, fill: faint)[#c.ordinal],
    text(size: 9pt)[#c.title],
    align(right)[#context {
      set text(size: 8pt, fill: faint)
      let found = query(label("ch" + str(c.ordinal)))
      if found.len() > 0 { found.first().location().page() }
    }],
  )
  #v(2mm)
]

// -------------------------------------------------------------- chapters
#for c in data.chapters [
  #chapter-head.update(c.quest)
  #pagebreak()

  #v(8mm)
  #text(size: 6.8pt, tracking: 2pt, fill: acc)[#upper[Chapter #ordinal(c.ordinal)]]
  #v(3mm)
  #heading(level: 2, outlined: false)[#c.title] #label("ch" + str(c.ordinal))
  #v(6mm)

  #eval(c.body_typst, mode: "markup")

  #v(5mm)
  #line(length: 42mm, stroke: (thickness: 0.4pt, paint: rule))
  #v(2mm)
  #text(size: 7.4pt, fill: faint)[
    Cited: #cite-label(c.citations.map(x => x.id)).
  ]
]

// ------------------------------------------------------------------- map
#chapter-head.update(data.title)
#pagebreak()
#text(size: 6.8pt, tracking: 2pt, fill: acc)[#upper[Map of the week]]
#v(4mm)
#text(size: 15pt)[Where the week went]
#v(4mm)

#let days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
#let lanes = ()
#for c in data.chapters {
  let existing = lanes.position(l => l.quest == c.quest)
  if existing == none {
    lanes.push((quest: c.quest, segments: (c,)))
  } else {
    lanes.at(existing).segments.push(c)
  }
}

#grid(
  columns: (17mm,) + (1fr,) * 7,
  gutter: 1.4mm,
  [],
  ..days.enumerate().map(((i, d)) => align(center)[
    #text(size: 6.2pt, fill: if i >= 5 { luma(150) } else { acc })[#d]
  ]),
)

#v(1.5mm)

#for lane in lanes [
  #grid(
    columns: (17mm,) + (1fr,) * 7,
    gutter: 1.4mm,
    text(size: 6.2pt)[#lane.quest],
    ..{
      let cells = ()
      let day = 0
      for segment in lane.segments {
        while day < segment.start_day {
          cells.push([])
          day += 1
        }
        let fill = if segment.label == "the dead end" { none } else if segment.label == "the detour" { luma(160) } else { acc }
        cells.push(grid.cell(colspan: segment.span)[
          #box(
            width: 100%,
            height: 3.4pt,
            fill: fill,
            stroke: if fill == none { (thickness: 0.5pt, paint: acc) } else { none },
            radius: 0.8pt,
          )
        ])
        day += segment.span
      }
      while day < 7 {
        cells.push([])
        day += 1
      }
      cells
    },
  )
  #v(1.6mm)
]

#v(3mm)
#line(length: 100%, stroke: (thickness: 0.4pt, paint: rule))
#v(2mm)
#text(size: 6.2pt, fill: faint)[
  #text(fill: acc)[■] breakthrough or rescue
  #h(5pt) #text(fill: luma(160))[■] detour
  #h(5pt) #text(fill: luma(205))[■] dead end
  #h(5pt) - Sat and Sun marked grey
]

// ------------------------------------------------------------------ cast
#chapter-head.update(data.title)
#pagebreak()
#text(size: 6.8pt, tracking: 2pt, fill: acc)[#upper[Dramatis personae]]
#v(4mm)

#let cast-group(title, rows, show-rate: false) = {
  let out = (
    table.cell(colspan: 3)[
      #v(2mm)
      #text(size: 6.4pt, tracking: 1.2pt, fill: acc)[#upper[#title]]
    ],
  )
  for r in rows {
    out.push(text(size: 8pt, font: mono)[#r.name])
    if show-rate {
      out.push(align(right)[#str(r.count)])
      out.push(align(right)[#(str(calc.round(r.failure_rate * 100)) + "%")])
    } else {
      out.push(table.cell(colspan: 2, align: right)[#str(r.count)])
    }
  }
  out
}

#table(
  columns: (1fr, 14mm, 14mm),
  stroke: (bottom: 0.4pt + rule),
  inset: (y: 1.1mm),
  ..cast-group("Tools", data.cast.tools, show-rate: true),
  ..cast-group("Places", data.cast.paths),
  ..cast-group("Repositories", data.cast.repos),
  ..cast-group("People", data.cast.people),
  ..cast-group("Services", data.cast.services),
)

// --------------------------------------------------------------- appendix
#chapter-head.update(data.title)
#pagebreak()
#text(size: 6.8pt, tracking: 2pt, fill: acc)[#upper[Appendix: the ledger]]
#v(2mm)
#text(size: 7.6pt, fill: faint)[Every event the book cites, in order. Uncited events are not printed.]

#v(4mm)
#let appendix-rows = ()
#let last-day = ""
#for a in data.appendix {
  if a.day != last-day {
    appendix-rows.push(table.cell(colspan: 4)[
      #v(2mm)
      #text(size: 6.4pt, tracking: 1.2pt, fill: acc)[#a.day]
    ])
    last-day = a.day
  }
  appendix-rows.push(text(size: 6.4pt, font: mono)[#a.id])
  appendix-rows.push(text(size: 6.4pt, font: mono)[#a.ts.slice(11, 16)])
  appendix-rows.push(text(size: 6.4pt, fill: faint)[#str(a.chapter)])
  appendix-rows.push(text(size: 7pt)[#a.summary])
}

#table(
  columns: (10mm, 11mm, 8mm, 1fr),
  stroke: (bottom: 0.3pt + rule),
  inset: (y: 0.9mm),
  table.header(
    text(size: 6.2pt, fill: luma(120))[Event],
    text(size: 6.2pt, fill: luma(120))[UTC],
    text(size: 6.2pt, fill: luma(120))[Ch.],
    text(size: 6.2pt, fill: luma(120))[Summary],
  ),
  ..appendix-rows,
)

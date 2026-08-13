/**
 * Loading placeholders shaped like the content they replace.
 *
 * A spinner says "something is happening"; a skeleton says "cards are coming
 * and here is where they'll be". It also stops the layout jumping when data
 * lands, which matters most on the free tier where a cold start can take the
 * better part of a minute.
 */
export function SkeletonCard() {
  return (
    <div className="ipo-card skeleton-card" aria-hidden="true">
      <div className="ipo-head">
        <div style={{ flex: 1 }}>
          <div className="sk sk-line" style={{ width: "68%", height: 15 }} />
          <div className="sk sk-line" style={{ width: "34%", height: 11, marginTop: 7 }} />
        </div>
        <div className="sk sk-line" style={{ width: 84, height: 28, borderRadius: 8 }} />
      </div>

      <div className="badges">
        <div className="sk sk-line" style={{ width: 56, height: 18, borderRadius: 999 }} />
        <div className="sk sk-line" style={{ width: 74, height: 18, borderRadius: 999 }} />
      </div>

      <div className="stats">
        {[0, 1, 2, 3].map((i) => (
          <div key={i}>
            <div className="sk sk-line" style={{ width: "56%", height: 9 }} />
            <div className="sk sk-line" style={{ width: "76%", height: 14, marginTop: 6 }} />
          </div>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div className="sk" style={{ width: 62, height: 62, borderRadius: "50%" }} />
        <div style={{ flex: 1 }}>
          <div className="sk sk-line" style={{ width: "50%", height: 10 }} />
          <div className="sk sk-line" style={{ width: "70%", height: 10, marginTop: 6 }} />
        </div>
      </div>
    </div>
  );
}

export function SkeletonGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="grid">
      {Array.from({ length: count }, (_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

type ProgressPillProps = {
  current: number;
  total: number;
};

export function ProgressPill({ current, total }: ProgressPillProps) {
  return (
    <div className="progress-pill" aria-label={`Step ${current} of ${total}`}>
      <strong>
        {current} of {total}
      </strong>
      <span aria-hidden="true">
        {Array.from({ length: total }).map((_, index) => (
          <i key={index} className={index < current ? "active" : ""} />
        ))}
      </span>
    </div>
  );
}

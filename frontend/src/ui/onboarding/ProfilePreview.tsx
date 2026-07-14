import { Calendar, Camera, Heart, UserRound } from "lucide-react";

const rows = [
  { icon: UserRound, label: "Name", value: "—" },
  { icon: Calendar, label: "Date of birth", value: "—" },
  { icon: Heart, label: "Interested in", value: "—" },
  { icon: Camera, label: "Photos", value: "—" }
];

export function ProfilePreview() {
  return (
    <aside className="profile-preview" aria-label="Profile so far">
      <header>
        <h2>Profile so far</h2>
        <span aria-hidden="true">›</span>
      </header>
      <div>
        {rows.map(({ icon: Icon, label, value }) => (
          <p key={label}>
            <span aria-hidden="true">
              <Icon size={22} />
            </span>
            <strong>{label}</strong>
            <em>{value}</em>
          </p>
        ))}
      </div>
    </aside>
  );
}

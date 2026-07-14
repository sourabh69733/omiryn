import { Calendar, Camera, Heart, MapPin, UserRound } from "lucide-react";

export type ProfilePreviewValues = {
  name?: string;
  dob?: string;
  interested?: string;
  location?: string;
  photos?: string;
};

type ProfilePreviewProps = {
  values: ProfilePreviewValues;
};

export function ProfilePreview({ values }: ProfilePreviewProps) {
  const rows = [
    { icon: UserRound, label: "Name", value: values.name || "—" },
    { icon: Calendar, label: "Date of birth", value: values.dob || "—" },
    { icon: Heart, label: "Interested in", value: values.interested || "—" },
    { icon: MapPin, label: "Location", value: values.location || "—" },
    { icon: Camera, label: "Photos", value: values.photos || "—" }
  ];

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

import { useEffect, useState, type ReactNode } from "react";

type AvatarImageProps = {
  alt?: string;
  fallback: ReactNode;
  src?: string | null;
};

export function AvatarImage({ alt = "", fallback, src }: AvatarImageProps) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (!src || failed) return <>{fallback}</>;

  return <img src={src} alt={alt} referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}

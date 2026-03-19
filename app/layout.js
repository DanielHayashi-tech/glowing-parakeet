import "./globals.css";

export const metadata = {
  title: "Corre Cortes Hub",
  description: "Local Garmin and training dashboard backed by SQLite."
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

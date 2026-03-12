import "./globals.css";

export const metadata = {
  title: "AI Study Partner",
  description: "Personal GenAI Tutor",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

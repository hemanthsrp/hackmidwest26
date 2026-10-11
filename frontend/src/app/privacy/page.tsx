import Link from "next/link";

export default function PrivacyPage() {
  return (
    <main className="legal-page">
      <Link className="text-button" href="/">
        ← Back to Folio
      </Link>
      <p className="eyebrow">BETA DATA NOTICE</p>
      <h1>Privacy at Folio</h1>
      <p className="legal-updated">Last updated October 11, 2026</p>

      <section>
        <h2>What the public demo uses</h2>
        <p>
          You can browse the demo without an account. A stock research request
          sends the ticker you selected to Folio so the server can retrieve
          stored source records. The theme preference is saved in your browser.
          The demo assistant uses scripted examples; it does not save a chat
          history.
        </p>
      </section>

      <section>
        <h2>If account access is enabled</h2>
        <p>
          Folio stores the account details needed to sign in, including your
          email address, display name, password hash or identity-provider link,
          preferences, notification settings, and any research memories you
          choose to save. Sessions use a revocable browser cookie and a server
          registry. Passwords are stored as salted hashes.
        </p>
        <p>
          Account holders can export their account data or request deletion in
          settings. Deletion removes account-linked research records. Public
          source evidence is shared research data and is not removed when one
          account is deleted.
        </p>
        <p>
          If you connect Robinhood, you authorize it directly through its
          Trading MCP consent flow; Folio never receives your Robinhood
          password. Robinhood&apos;s consent includes broad read access to your
          accounts, account numbers, positions, balances, and transaction
          history. Folio calls only account, portfolio, and equity-position
          read tools, discards account numbers and transaction history, and
          stores a normalized portfolio snapshot plus an encrypted refresh
          token until you disconnect or delete your Folio account. Folio blocks
          order placement, cancellation, and other account-changing tools.
          Disconnecting Folio deletes its grant and saved portfolio snapshot;
          separately revoke access in Robinhood account settings.
        </p>
      </section>

      <section>
        <h2>Research assistant and service providers</h2>
        <p>
          Signed-in assistant messages are processed to answer the current
          request and are not saved as conversation history by Folio. When a
          hosted model or judgment provider is enabled, the request and the
          selected research evidence are sent to that provider. Sign-in,
          email delivery, and data-source providers receive the information
          needed for their enabled feature. Their own privacy terms apply.
        </p>
      </section>

      <section>
        <h2>Retention and beta limits</h2>
        <p>
          Account data remains until the account is deleted. Source records are
          retained in the shared research store under the beta operator’s
          retention policy. Folio does not request brokerage passwords or place
          trades. Never enter brokerage credentials into Folio; use only the
          official Robinhood consent screen if you choose to connect an account.
        </p>
        <p>
          Hosting providers may process connection and service logs to operate
          the app. The exact retention period depends on the selected hosting
          configuration and must be published by the beta operator before
          public sign-up opens.
        </p>
      </section>

      <p className="legal-draft">
        This is Folio’s product data notice for the beta. The operator must
        review it against the final hosting, provider, and retention settings
        before enabling account registration.
      </p>
    </main>
  );
}

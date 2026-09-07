"use client";

import { Modal } from "@mantine/core";
import {
  IconArrowUpRight,
  IconBrandGithub,
  IconClipboardText,
  IconCloud,
  IconDatabase,
  IconDeviceLaptop,
  IconFolderCode,
  IconMaximize,
  IconMenu2,
  IconMoon,
  IconServer,
  IconSun,
  IconTerminal2,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { AppLogo } from "@/shared/components/AppLogo";
import classes from "../HomePage.module.css";
import { LocaleSwitcher } from "./LocaleSwitcher";
import type { HomePageContainerOutput } from "../containers/useHomePageContainer";

const DOCS_URL =
  "https://github.com/azents/azents/blob/main/docs/azents/INDEX.md";
const GITHUB_URL = "https://github.com/azents/azents";
const PULLS_URL = "https://github.com/azents/azents/pulls";
const ISSUES_URL = "https://github.com/azents/azents/issues";
const LICENSE_URL = "https://github.com/azents/azents/blob/main/LICENSE";

function ExternalArrow(): React.ReactElement {
  return <IconArrowUpRight aria-hidden="true" size="1em" stroke={1.7} />;
}

interface ThemeToggleProps {
  mode: HomePageContainerOutput["mode"];
  onToggle: () => void;
}

function ThemeToggle({ mode, onToggle }: ThemeToggleProps): React.ReactElement {
  const t = useTranslations("landing");
  const label =
    mode === "dark" ? t("theme.switchToLight") : t("theme.switchToDark");

  return (
    <button
      type="button"
      className={classes.themeToggle}
      onClick={onToggle}
      aria-label={label}
      title={label}
    >
      {mode === "dark" ? (
        <IconSun aria-hidden="true" size="1rem" stroke={1.7} />
      ) : (
        <IconMoon aria-hidden="true" size="1rem" stroke={1.7} />
      )}
      <span>{mode === "dark" ? t("theme.light") : t("theme.dark")}</span>
    </button>
  );
}

interface ProductCaptureProps {
  className?: string;
  priority?: boolean;
}

function ProductCapture({
  className,
  priority = false,
}: ProductCaptureProps): React.ReactElement {
  const t = useTranslations("landing");

  return (
    <picture className={className}>
      <source
        media="(max-width: 37.5rem)"
        srcSet="/homepage/azents-component-mobile.webp"
        width={324}
        height={415}
      />
      <Image
        src="/homepage/azents-component-desktop.webp"
        alt={t("product.alt")}
        width={1000}
        height={451}
        priority={priority}
        sizes="(max-width: 37.5rem) calc(100vw - 2rem), (max-width: 75rem) calc(100vw - 14rem), 62.5rem"
        className={classes.captureImage}
      />
    </picture>
  );
}

export function HomePageContent({
  captureOpen,
  menuOpen,
  mode,
  onCloseCapture,
  onCloseMenu,
  onOpenCapture,
  onToggleMenu,
  onToggleTheme,
}: HomePageContainerOutput): React.ReactElement {
  const t = useTranslations("landing");

  return (
    <div className={classes.page}>
      <a className={classes.skipLink} href="#main-content">
        {t("accessibility.skip")}
      </a>

      <header className={classes.header}>
        <div className={`${classes.container} ${classes.nav}`}>
          <div className={classes.brandGroup}>
            <AppLogo href="/" />
            <span className={classes.brandTag}>{t("brand.tag")}</span>
          </div>

          <nav
            id="landing-navigation"
            className={`${classes.navLinks} ${menuOpen ? classes.navLinksOpen : ""}`}
            aria-label={t("nav.label")}
          >
            <a href="#continuity" onClick={onCloseMenu}>
              {t("nav.why")}
            </a>
            <a href="#workflows" onClick={onCloseMenu}>
              {t("nav.workflows")}
            </a>
            <a href="#system" onClick={onCloseMenu}>
              {t("nav.system")}
            </a>
            <a href={DOCS_URL} target="_blank" rel="noreferrer">
              {t("nav.docs")} <ExternalArrow />
            </a>
            <a
              className={classes.navSource}
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
            >
              <IconBrandGithub aria-hidden="true" size="1rem" stroke={1.7} />
              {t("nav.github")} <ExternalArrow />
            </a>
            <div className={classes.mobileLocaleControl}>
              <LocaleSwitcher />
            </div>
          </nav>

          <div className={classes.navActions}>
            <div className={classes.localeControl}>
              <LocaleSwitcher />
            </div>
            <ThemeToggle mode={mode} onToggle={onToggleTheme} />
            <button
              type="button"
              className={classes.menuToggle}
              aria-expanded={menuOpen}
              aria-controls="landing-navigation"
              aria-label={menuOpen ? t("menu.close") : t("menu.open")}
              onClick={onToggleMenu}
            >
              {menuOpen ? (
                <IconX aria-hidden="true" size="1.25rem" stroke={1.6} />
              ) : (
                <IconMenu2 aria-hidden="true" size="1.25rem" stroke={1.6} />
              )}
            </button>
          </div>
        </div>
      </header>

      <main id="main-content">
        <section className={`${classes.container} ${classes.hero}`}>
          <div className={classes.heroTop}>
            <div>
              <p className={classes.eyebrow}>
                <span className={classes.signal} aria-hidden="true" />
                {t("hero.eyebrow")}
                <span className={classes.eyebrowSlash}>/</span>
                {t("hero.buildInPublic")}
              </p>
              <h1>
                {t("hero.title")}
                <br />
                <span>{t("hero.titleAccent")}</span>
              </h1>
            </div>
            <div className={classes.heroIntro}>
              <p className={classes.heroLead}>{t("hero.lead")}</p>
              <p>{t("hero.body")}</p>
              <div className={classes.actions}>
                <a
                  className={`${classes.button} ${classes.buttonPrimary}`}
                  href={DOCS_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("hero.docsCta")} <ExternalArrow />
                </a>
                <a
                  className={classes.inlineLink}
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("hero.sourceCta")} <ExternalArrow />
                </a>
              </div>
            </div>
          </div>

          <div className={classes.productStage}>
            <span
              className={`${classes.cross} ${classes.crossTopLeft}`}
              aria-hidden="true"
            >
              +
            </span>
            <span
              className={`${classes.cross} ${classes.crossTopRight}`}
              aria-hidden="true"
            >
              +
            </span>
            <span
              className={`${classes.cross} ${classes.crossBottomLeft}`}
              aria-hidden="true"
            >
              +
            </span>
            <span
              className={`${classes.cross} ${classes.crossBottomRight}`}
              aria-hidden="true"
            >
              +
            </span>

            <aside className={classes.stageGuide}>
              <p className={classes.stageLabel}>{t("product.stageLabel")}</p>
              <div className={classes.guideItem}>
                <span>01</span>
                <strong>{t("product.guide1Title")}</strong>
                <p>{t("product.guide1Body")}</p>
              </div>
              <div className={classes.guideItem}>
                <span>02</span>
                <strong>{t("product.guide2Title")}</strong>
                <p>{t("product.guide2Body")}</p>
              </div>
              <div className={classes.guideItem}>
                <span>03</span>
                <strong>{t("product.guide3Title")}</strong>
                <p>{t("product.guide3Body")}</p>
              </div>
              <p className={classes.guideBottom}>{t("product.guideBottom")}</p>
            </aside>

            <div
              className={classes.productWindow}
              role="group"
              aria-label={t("product.windowAria")}
            >
              <div className={classes.windowBar}>
                <span className={classes.windowDots} aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
                <span>{t("product.windowTitle")}</span>
                <span className={classes.sourceLabel}>
                  {t("product.sourceLabel")}
                </span>
              </div>
              <button
                type="button"
                className={classes.captureButton}
                aria-label={t("product.open")}
                onClick={onOpenCapture}
              >
                <ProductCapture priority />
                <span className={classes.expandLabel}>
                  <IconMaximize aria-hidden="true" size="0.9rem" stroke={1.6} />
                  {t("product.expand")}
                </span>
              </button>
            </div>
          </div>

          <div className={classes.stageCaption}>
            <span>{t("product.captionDisclosure")}</span>
            <span>{t("product.captionContents")}</span>
          </div>
          <div className={classes.heroFacts}>
            <span>{t("product.factSessions")}</span>
            <span>{t("product.factTools")}</span>
            <span>{t("product.factRuntimes")}</span>
          </div>
        </section>

        <section
          className={`${classes.container} ${classes.continuity}`}
          id="continuity"
          aria-labelledby="continuity-title"
        >
          <div className={classes.sectionMarker}>
            <span>{t("continuity.marker")}</span>
            <span className={classes.markerLine} />
          </div>
          <div className={classes.continuityGrid}>
            <h2 id="continuity-title">
              {t("continuity.title")}
              <br />
              <span>{t("continuity.titleAccent")}</span>
            </h2>
            <article className={classes.benefit}>
              <IconDeviceLaptop
                aria-hidden="true"
                size="1.35rem"
                stroke={1.4}
              />
              <h3>{t("continuity.keepRunningTitle")}</h3>
              <p>{t("continuity.keepRunningBody")}</p>
            </article>
            <article className={classes.benefit}>
              <IconClipboardText
                aria-hidden="true"
                size="1.35rem"
                stroke={1.4}
              />
              <h3>{t("continuity.keepContextTitle")}</h3>
              <p>{t("continuity.keepContextBody")}</p>
            </article>
            <article className={classes.benefit}>
              <IconServer aria-hidden="true" size="1.35rem" stroke={1.4} />
              <h3>{t("continuity.keepCloseTitle")}</h3>
              <p>{t("continuity.keepCloseBody")}</p>
            </article>
          </div>
        </section>

        <section className={classes.workflows} id="workflows">
          <div className={classes.container}>
            <div className={classes.sectionMarker}>
              <span>{t("workflows.marker")}</span>
              <span className={classes.markerLine} />
              <span className={classes.markerEnd}>
                {t("workflows.markerEnd")}
              </span>
            </div>
            <div className={classes.proofHeading}>
              <h2>
                {t("workflows.title")}
                <br />
                {t("workflows.titleSecond")}
              </h2>
              <div>
                <p>{t("workflows.body")}</p>
                <a
                  className={classes.inlineLink}
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("workflows.referenceLink")} <ExternalArrow />
                </a>
              </div>
            </div>

            <div className={classes.workstreamGrid}>
              <article
                className={`${classes.workstream} ${classes.workstreamFeatured}`}
              >
                <div className={classes.workstreamTop}>
                  <span>{t("workflows.referenceLabel")}</span>
                  <b>01</b>
                </div>
                <IconFolderCode
                  aria-hidden="true"
                  size="1.5rem"
                  stroke={1.35}
                />
                <h3>{t("workflows.softwareTitle")}</h3>
                <p>{t("workflows.softwareBody")}</p>
                <div className={classes.workstreamFlow}>
                  <span>{t("workflows.softwareFlow1")}</span>
                  <i>→</i>
                  <span>{t("workflows.softwareFlow2")}</span>
                  <i>→</i>
                  <span>{t("workflows.softwareFlow3")}</span>
                </div>
                <a href={PULLS_URL} target="_blank" rel="noreferrer">
                  {t("workflows.softwareLink")} <ExternalArrow />
                </a>
              </article>
              <article className={classes.workstream}>
                <div className={classes.workstreamTop}>
                  <span>{t("workflows.capabilityLabel")}</span>
                  <b>02</b>
                </div>
                <IconCloud aria-hidden="true" size="1.5rem" stroke={1.35} />
                <h3>{t("workflows.systemsTitle")}</h3>
                <p>{t("workflows.systemsBody")}</p>
                <div className={classes.workstreamFlow}>
                  <span>{t("workflows.systemsFlow1")}</span>
                  <i>→</i>
                  <span>{t("workflows.systemsFlow2")}</span>
                  <i>→</i>
                  <span>{t("workflows.systemsFlow3")}</span>
                </div>
                <small>{t("workflows.capabilityNote")}</small>
              </article>
              <article className={classes.workstream}>
                <div className={classes.workstreamTop}>
                  <span>{t("workflows.capabilityLabel")}</span>
                  <b>03</b>
                </div>
                <IconDatabase aria-hidden="true" size="1.5rem" stroke={1.35} />
                <h3>{t("workflows.researchTitle")}</h3>
                <p>{t("workflows.researchBody")}</p>
                <div className={classes.workstreamFlow}>
                  <span>{t("workflows.researchFlow1")}</span>
                  <i>→</i>
                  <span>{t("workflows.researchFlow2")}</span>
                  <i>→</i>
                  <span>{t("workflows.researchFlow3")}</span>
                </div>
                <small>{t("workflows.capabilityNote")}</small>
              </article>
            </div>

            <div className={classes.publicProof}>
              <div>
                <span>{t("workflows.proofLabel")}</span>
                <p>{t("workflows.proofBody")}</p>
              </div>
              <div className={classes.proofLinks}>
                <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                  <span>{t("workflows.sourceCode")}</span>
                  <b>
                    {t("nav.github")} <ExternalArrow />
                  </b>
                </a>
                <a href={DOCS_URL} target="_blank" rel="noreferrer">
                  <span>{t("workflows.architecture")}</span>
                  <b>
                    {t("nav.docs")} <ExternalArrow />
                  </b>
                </a>
                <a href={PULLS_URL} target="_blank" rel="noreferrer">
                  <span>{t("workflows.changes")}</span>
                  <b>
                    {t("workflows.pullRequests")} <ExternalArrow />
                  </b>
                </a>
              </div>
            </div>
          </div>
        </section>

        <section
          className={`${classes.container} ${classes.system}`}
          id="system"
        >
          <div className={classes.sectionMarker}>
            <span>{t("system.marker")}</span>
            <span className={classes.markerLine} />
            <a href={DOCS_URL} target="_blank" rel="noreferrer">
              {t("system.docsLink")} <ExternalArrow />
            </a>
          </div>
          <div className={classes.systemHeading}>
            <h2>
              {t("system.title")}
              <br />
              {t("system.titleSecond")}
            </h2>
            <p>{t("system.body")}</p>
          </div>
          <div
            className={classes.systemDiagram}
            role="img"
            aria-label={t("system.diagramAria")}
          >
            <div className={classes.diagramTop}>
              <span>{t("system.diagramLabel")}</span>
              <span>{t("system.separation")}</span>
            </div>
            <div className={classes.diagramLayout}>
              <div className={classes.systemNode}>
                <span className={classes.nodeLabel}>
                  {t("system.controlPlane")}
                </span>
                <div className={classes.nodeTitle}>
                  <IconDatabase
                    aria-hidden="true"
                    size="1.75rem"
                    stroke={1.25}
                  />
                  <h3>{t("system.engineTitle")}</h3>
                </div>
                <p>{t("system.engineBody")}</p>
                <div className={classes.eventRail}>
                  <span>{t("system.history")}</span>
                  <div aria-hidden="true">
                    <i />
                    <b />
                    <i />
                    <b />
                    <i />
                    <b />
                    <i />
                  </div>
                </div>
              </div>
              <div className={classes.connection} aria-hidden="true">
                <span>{t("system.toolCalls")}</span>
                <div>⟶</div>
                <div>⟵</div>
                <span>{t("system.results")}</span>
              </div>
              <div className={`${classes.systemNode} ${classes.runtimeNode}`}>
                <span className={classes.nodeLabel}>
                  {t("system.execution")}
                </span>
                <div className={classes.nodeTitle}>
                  <IconTerminal2
                    aria-hidden="true"
                    size="1.75rem"
                    stroke={1.25}
                  />
                  <h3>{t("system.runtimeTitle")}</h3>
                </div>
                <p>{t("system.runtimeBody")}</p>
                <div className={classes.runtimeTools}>
                  <span>{t("system.files")}</span>
                  <span>{t("system.shell")}</span>
                  <span>{t("system.tools")}</span>
                  <span>{t("system.compute")}</span>
                </div>
              </div>
            </div>
            <div className={classes.diagramBottom}>
              <span>{t("system.context")}</span>
              <span>⟷</span>
              <span>{t("system.operations")}</span>
            </div>
          </div>
          <p className={classes.diagramNote}>{t("system.note")}</p>
        </section>

        <section
          className={`${classes.container} ${classes.project}`}
          id="project"
        >
          <div className={classes.sectionMarker}>
            <span>{t("project.marker")}</span>
            <span className={classes.markerLine} />
          </div>
          <div className={classes.projectGrid}>
            <div>
              <h2>
                {t("project.title")}
                <br />
                {t("project.titleSecond")}
              </h2>
              <p className={classes.projectCopy}>{t("project.body")}</p>
              <div className={classes.projectActions}>
                <a
                  className={`${classes.button} ${classes.buttonSecondary}`}
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("project.repositoryCta")} <ExternalArrow />
                </a>
                <a
                  className={classes.inlineLink}
                  href={ISSUES_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("project.feedbackCta")} <ExternalArrow />
                </a>
              </div>
              <div className={classes.projectMeta}>
                <span>{t("project.mit")}</span>
                <span>{t("project.selfHosted")}</span>
                <span>{t("project.workInProgress")}</span>
              </div>
            </div>
            <div className={classes.focusList}>
              <p className={classes.focusLabel}>{t("project.focusLabel")}</p>
              <div>
                <span>{t("project.focus1")}</span>
                <span>01</span>
              </div>
              <div>
                <span>{t("project.focus2")}</span>
                <span>02</span>
              </div>
              <div>
                <span>{t("project.focus3")}</span>
                <span>03</span>
              </div>
              <div>
                <span>{t("project.focus4")}</span>
                <span>04</span>
              </div>
              <p>{t("project.focusNote")}</p>
            </div>
          </div>

          <div className={classes.faq}>
            <h3>{t("faq.title")}</h3>
            <div>
              <details>
                <summary>{t("faq.question1")}</summary>
                <p>{t("faq.answer1")}</p>
              </details>
              <details>
                <summary>{t("faq.question2")}</summary>
                <p>{t("faq.answer2")}</p>
              </details>
              <details>
                <summary>{t("faq.question3")}</summary>
                <p>{t("faq.answer3")}</p>
              </details>
              <details>
                <summary>{t("faq.question4")}</summary>
                <p>
                  {t("faq.answer4")}{" "}
                  <a href={DOCS_URL} target="_blank" rel="noreferrer">
                    {t("faq.docsLink")}
                  </a>{" "}
                  ·{" "}
                  <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                    {t("faq.repositoryLink")}
                  </a>
                </p>
              </details>
            </div>
          </div>
        </section>

        <section className={classes.closing}>
          <div className={`${classes.container} ${classes.closingInner}`}>
            <div>
              <span className={classes.closingLabel}>{t("closing.label")}</span>
              <h2>
                {t("closing.title")}
                <br />
                {t("closing.titleSecond")}
              </h2>
            </div>
            <div>
              <a
                className={`${classes.button} ${classes.buttonPrimary}`}
                href={DOCS_URL}
                target="_blank"
                rel="noreferrer"
              >
                {t("closing.cta")} <ExternalArrow />
              </a>
              <p>{t("closing.note")}</p>
            </div>
          </div>
        </section>
      </main>

      <footer className={`${classes.container} ${classes.footer}`}>
        <div className={classes.footerMain}>
          <AppLogo href="/" />
          <span>{t("footer.tagline")}</span>
          <div>
            <a href={GITHUB_URL} target="_blank" rel="noreferrer">
              {t("nav.github")} <ExternalArrow />
            </a>
            <a href={LICENSE_URL} target="_blank" rel="noreferrer">
              {t("footer.license")} <ExternalArrow />
            </a>
          </div>
        </div>
        <div className={classes.footerNote}>
          <span>{t("footer.buildInPublic")}</span>
          <span>{t("footer.disclosure")}</span>
        </div>
      </footer>

      <Modal
        opened={captureOpen}
        onClose={onCloseCapture}
        title={t("product.dialogTitle")}
        size="min(94vw, 75rem)"
        centered
        classNames={{
          body: classes.modalBody,
          content: classes.modalContent,
          header: classes.modalHeader,
          title: classes.modalTitle,
        }}
      >
        <ProductCapture className={classes.modalPicture} />
        <p className={classes.modalDisclosure}>
          {t("product.captionDisclosure")}
        </p>
      </Modal>
    </div>
  );
}

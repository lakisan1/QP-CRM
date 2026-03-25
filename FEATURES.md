# QP-CRM Complete Feature List 🌟

This page contains a comprehensive list of all the features implemented in the QP-CRM application, categorized by module. Feel free to add new features here as the application updates!

## 🏷️ Pricing & Product Management (Pricing App)
- **Dynamic Price Calculation**: Automatically calculate sale prices based on margins, fixed costs, taxes, and customizable rounding rules.
- **Price History Tracking**: Track price history records automatically after every modification.
- **Quick Price Updates**: Bulk edit mode to rapidly update base costs and margins for multiple products on a single page.
- **Extensive Product Details**: Manage items by categories, brands, default presets, and custom properties.
- **Product Photos**: Upload product imagery from direct URL links or local files with built-in format conversion to standard formats.
- **Advanced Filtering & Sorting**: Powerful tabular interfaces with sorting by name, price, brand, and categorical filters.
- **Comparison Tool**: Directly compare the prices, specs, and origins of multiple products out of the box.

## 📄 Offers & Quotations (Offer App)
- **Professional PDF Generation**: Generate dynamic, styled, brand-ready PDFs natively from the app.
- **Markdown Support for Descriptions**: Rich-text editing on product descriptions within offers using EasyMDE; beautifully formatted text (bold, lists, etc.) rendered seamlessly into the final PDF.
- **Email Integration**: Send custom styled quotation emails with PDF attachments directly from the app interface.
- **Line-item & Global Discounts**: Apply percentage discounts across an entire quote, toggle item-specific per-line discounts dynamically, and layer additional "Special Discounts" on top of existing subtotals for greater pricing flexibility.
- **Live NBS Exchange Rates**: Connect to the National Bank of Serbia (NBS) API for automatic fetching and conversion of currency exchange rates into base pricing.
- **Client Management Details**: Customizable, default mandatory fields for CRM records including PIB, MB, multiple emails parsing, and direct persistence of client data for repeat offers.
- **Quick Offer Presets**: Save, reload, and default offer templates over existing workflows.
- **Visual Rearrangement**: Reorder line-items inside existing quotations effortlessly.

## ⚙️ Administration & Settings (Admin Panel)
- **Live PDF Template Editor**: In-app HTML/CSS code editor to dynamically create, preview, and update your PDF quotation templates without restarting the server.
- **Branding Personalization**: Upload custom system Favicons, Application Logos, and predefined Footer snippets for uniform branding on exported assets.
- **Global Text & UI Presets**: Set unified system settings like default global VAT, delivery terms, standard payment texts, validity days, and application date formats.
- **Integrated File Management Utility**: Execute cleanups to automatically prune orphaned product images and keep server assets trim.
- **Role-based Authentication**: Password updates and gated accesses for the underlying Price, Offer, and Admin environments.

## 💻 Tech & System Foundation
- **Unified Progressive Web App (PWA)**: Desktop installation support via Chrome, providing seamless native-feeling windows mapped to your server IP.
- **Fast Deployments & Database Management**: Quick Linux deployment scripts (`run_apps.sh`) handling dependency management and instant auto-start servers.
- **Backup & Restore System**: 1-click administrative utilities for executing comprehensive full-system backups (including databases, user-uploaded images, logos, assets) or restoring from legacy snapshots.
- **Standalone Read-Only Instances**: Zero-login viewer modules for basic users to inspect live pricing out-of-the-box. 

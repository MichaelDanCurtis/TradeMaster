import AppKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var status = NSTextField(labelWithString: "Starting TradeMaster…")
    var launcher: Process?
    var outputBuffer = Data()
    var startingView: NSStackView!
    var terminating = false
    let origin = URL(string: "http://127.0.0.1:18898/")!
    let dataURL = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("TradeMaster")

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "About TradeMaster", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(withTitle: "Open Logs", action: #selector(openLogs), keyEquivalent: "l").target = self
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit TradeMaster", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); menu.addItem(editItem); let edit = NSMenu(title: "Edit"); editItem.submenu = edit
        for (title, action, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        let viewItem = NSMenuItem(); menu.addItem(viewItem); let view = NSMenu(title: "View"); viewItem.submenu = view
        view.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r").target = self
        view.addItem(withTitle: "Open in Browser", action: #selector(openBrowser), keyEquivalent: "").target = self
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1500, height: 950), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "TradeMaster"
        window.minSize = NSSize(width: 900, height: 650)
        window.setFrameAutosaveName("TradeMasterMainWindow")
        window.center()
        let config = WKWebViewConfiguration()
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self; web.uiDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        window.backgroundColor = NSColor(calibratedWhite: 0.06, alpha: 1)
        let heading = NSTextField(labelWithString: "TradeMaster")
        heading.font = .boldSystemFont(ofSize: 28); heading.textColor = .white
        status.textColor = .lightGray; status.maximumNumberOfLines = 4; status.preferredMaxLayoutWidth = 600
        let logs = NSButton(title: "Open Logs", target: self, action: #selector(openLogs))
        let retry = NSButton(title: "Retry", target: self, action: #selector(start))
        startingView = NSStackView(views: [heading, status, logs, retry]); startingView.orientation = .vertical; startingView.spacing = 18
        let content = NSView(); window.contentView = content
        content.addSubview(web); content.addSubview(startingView)
        web.translatesAutoresizingMaskIntoConstraints = false; startingView.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            web.leadingAnchor.constraint(equalTo: content.leadingAnchor), web.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            web.topAnchor.constraint(equalTo: content.topAnchor), web.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            startingView.centerXAnchor.constraint(equalTo: content.centerXAnchor), startingView.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            startingView.widthAnchor.constraint(lessThanOrEqualToConstant: 650)
        ])
        web.isHidden = true; window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        start()
    }
    @objc func start() {
        if launcher?.isRunning == true { startingView.isHidden = true; web.isHidden = false; web.load(URLRequest(url: origin)); return }
        let resources = Bundle.main.resourceURL!
        status.stringValue = "Starting the bundled local services…"; web.isHidden = true; startingView.isHidden = false
        let process = Process(); launcher = process; outputBuffer = Data()
        process.executableURL = resources.appendingPathComponent("python/bin/python3.12")
        process.arguments = ["-u", resources.appendingPathComponent("desktop/runtime.py").path, "--resources", resources.path, "--data-dir", dataURL.path, "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONNOUSERSITE"] = "1"; env["PYTHONDONTWRITEBYTECODE"] = "1"; env["PYTHON_DOTENV_DISABLED"] = "1"
        // A Finder launch must not inherit a developer virtual environment.
        for key in ["PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"] { env.removeValue(forKey: key) }
        process.environment = env
        let pipe = Pipe(); process.standardOutput = pipe; process.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let bytes = handle.availableData
            guard !bytes.isEmpty else { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.consume(bytes) }
        }
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if self.terminating { NSApp.reply(toApplicationShouldTerminate: true); return }
                if process.terminationStatus != 0 && !self.status.stringValue.contains("could not") {
                    self.status.stringValue = "A local service stopped. Open Logs for details, then Retry."
                }
                self.web.isHidden = true; self.startingView.isHidden = false
            }
        }
        do { try process.run() } catch { status.stringValue = "Could not start TradeMaster: \(error.localizedDescription)" }
    }
    func consume(_ data: Data) {
        outputBuffer.append(data)
        while let range = outputBuffer.range(of: Data([10])) {
            let line = outputBuffer.subdata(in: 0..<range.lowerBound); outputBuffer.removeSubrange(0..<range.upperBound)
            guard let event = try? JSONSerialization.jsonObject(with: line) as? [String: String], let message = event["message"] else { continue }
            if event["state"] == "ready" {
                startingView.isHidden = true; web.isHidden = false; web.load(URLRequest(url: origin))
            } else { status.stringValue = message }
        }
        if outputBuffer.count > 65536 { outputBuffer.removeAll() }
    }
    @objc func reload() { web.reload() }
    @objc func openBrowser() { NSWorkspace.shared.open(origin) }
    @objc func openLogs() {
        let logs = dataURL.appendingPathComponent("logs")
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        NSWorkspace.shared.open(logs)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let launcher = launcher, launcher.isRunning else { return .terminateNow }
        if terminating { return .terminateLater }
        terminating = true; launcher.terminate()
        DispatchQueue.main.asyncAfter(deadline: .now() + 12) { NSApp.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
    func local(_ url: URL) -> Bool { url.scheme == "http" && url.host == "127.0.0.1" && url.port == 18898 }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if local(url) || url.scheme == "blob" { decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow) }
        else {
            if ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url, ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        return nil
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        status.stringValue = "The local dashboard could not load. Retry or open Logs."
        web.isHidden = true; startingView.isHidden = false
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.nameFieldStringValue = suggestedFilename
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.url : nil) }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        let alert = NSAlert(); alert.messageText = "Download did not complete"; alert.informativeText = error.localizedDescription
        alert.beginSheetModal(for: window)
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.urls : nil) }
    }
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()

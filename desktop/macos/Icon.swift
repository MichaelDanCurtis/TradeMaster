import AppKit
let directory = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
for size in [16,32,64,128,256,512,1024] {
    let image = NSImage(size: NSSize(width: size, height: size))
    image.lockFocus()
    let scale = CGFloat(size) / 1024
    let transform = NSAffineTransform(); transform.scale(by: scale); transform.concat()
    NSColor(calibratedRed: 0.07, green: 0.10, blue: 0.17, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 36,y: 36,width: 952,height: 952), xRadius: 210,yRadius: 210).fill()
    NSColor(calibratedRed: 0.28,green: 0.55,blue: 0.98,alpha: 1).setStroke()
    let line = NSBezierPath(); line.lineWidth = 40; line.lineJoinStyle = .round; line.lineCapStyle = .round
    line.move(to: NSPoint(x: 180,y: 300)); line.line(to: NSPoint(x: 335,y: 410)); line.line(to: NSPoint(x: 470,y: 330)); line.line(to: NSPoint(x: 650,y: 565)); line.line(to: NSPoint(x: 835,y: 735)); line.stroke()
    let text: NSString = "TM"
    text.draw(at: NSPoint(x: 164,y: 600),withAttributes: [.font:NSFont.boldSystemFont(ofSize:200),.foregroundColor:NSColor.white])
    image.unlockFocus()
    let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
    let png = bitmap.representation(using: .png,properties: [:])!
    if [16,32,128,256,512].contains(size) { try png.write(to: directory.appendingPathComponent("icon_\(size)x\(size).png")) }
    if [32,64,256,512,1024].contains(size) { try png.write(to: directory.appendingPathComponent("icon_\(size/2)x\(size/2)@2x.png")) }
}

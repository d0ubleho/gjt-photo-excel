import Foundation
import Vision
import ImageIO
import CoreGraphics
import UniformTypeIdentifiers

struct Detection: Codable {
    let text: String
    let x: Double, y: Double, w: Double, h: Double, confidence: Float
    init(_ text: String, _ rect: CGRect, _ confidence: Float = 1) {
        self.text = text
        (x,y,w,h) = (rect.minX, 1 - rect.maxY, rect.width, rect.height)
        self.confidence = confidence
    }
}
struct Scan: Codable {
    let lines: [Detection], codes: [Detection]
    let rotation: UInt32
    let width: Int, height: Int
}
func main() throws {
    let args = CommandLine.arguments
    guard args.count == 5, let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: args[2]) as CFURL, nil),
          let raw = CGImageSourceCreateThumbnailAtIndex(source, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: 2400
          ] as CFDictionary) else { throw CocoaError(.fileReadCorruptFile) }
    let mode = args[1]
    func rotated(_ angle: Int) -> CGImage {
        guard angle != 0 else { return raw }
        let sideways = angle % 180 != 0
        let w = sideways ? raw.height : raw.width, h = sideways ? raw.width : raw.height
        let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
        ctx.translateBy(x: Double(w)/2, y: Double(h)/2)
        ctx.rotate(by: Double(angle) * .pi / 180)
        ctx.draw(raw, in: CGRect(x: -Double(raw.width)/2, y: -Double(raw.height)/2, width: Double(raw.width), height: Double(raw.height)))
        return ctx.makeImage()!
    }
    var best = Scan(lines: [], codes: [], rotation: 0, width: raw.width, height: raw.height), bestScore = -1.0
    for angle in (mode == "photo" ? [0] : [0,90,270,180]) {
        let image = rotated(angle)
        let handler = VNImageRequestHandler(cgImage: image)
        let text = VNRecognizeTextRequest()
        text.revision = VNRecognizeTextRequestRevision3
        text.recognitionLevel = .accurate
        text.recognitionLanguages = ["ko-KR", "en-US"]
        text.usesLanguageCorrection = false
        text.usesCPUOnly = true
        let qr = VNDetectBarcodesRequest()
        qr.symbologies = [.qr]
        qr.usesCPUOnly = true
        if mode == "form" { try handler.perform([text]) }
        if mode == "sticker" { try handler.perform([text,qr]) }
        let lines = (text.results ?? []).compactMap { item in
            item.topCandidates(1).first.map { Detection($0.string, item.boundingBox, $0.confidence) }
        }
        let codes = (qr.results ?? []).compactMap { item in
            item.payloadStringValue.map { Detection($0, item.boundingBox) }
        }
        let labels = mode == "form" ? ["신청번호","신청부서","자산번호","수량","반납신청서","품명"] :
            ["자산번호","비품번호","품명","설치장소","사용부서","일련번호","구입일자"]
        let score = lines.reduce(0.0) { score, line in
            let t = line.text.filter { !$0.isWhitespace }
            let horizontal = line.w * Double(image.width) > line.h * Double(image.height)
            let base = Double(t.count) * Double(line.confidence) + Double(labels.filter { t.contains($0) }.count * 22)
            return score + base * (horizontal ? 1 : 0.15)
        } + Double(codes.filter { $0.x > 0.55 }.count * 70) + (angle == 0 ? 14 : 0)
        if score > bestScore {
            bestScore = score
            best = Scan(lines: lines, codes: codes, rotation: UInt32(angle), width: image.width, height: image.height)
        }
    }
    let out = URL(fileURLWithPath: args[3]) as CFURL
    guard let destination = CGImageDestinationCreateWithURL(out, UTType.jpeg.identifier as CFString, 1, nil) else {
        throw CocoaError(.fileWriteUnknown)
    }
    CGImageDestinationAddImage(destination, rotated(Int(best.rotation)), [kCGImageDestinationLossyCompressionQuality: 0.87] as CFDictionary)
    guard CGImageDestinationFinalize(destination) else { throw CocoaError(.fileWriteUnknown) }
    try JSONEncoder().encode(best).write(to: URL(fileURLWithPath: args[4]), options: .atomic)
}
do { try main() }
catch { FileHandle.standardError.write(Data("\(error as NSError)\n".utf8)); exit(1) }

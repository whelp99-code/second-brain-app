import Foundation
import XCTest
@testable import SecondBrainCore

final class APIContractTests: XCTestCase {
    func testUploadReceiptDecodesServerSnakeCaseContract() throws {
        let data = Data(
            #"{"upload_id":"u1","state":"queued","inbox_path":"inbox/uploads/note.md","content_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","bytes":4,"filename":"note.md","relative_path":"Docs/note.md","device_id":"mac-1"}"#.utf8
        )

        let receipt = try JSONDecoder().decode(UploadReceipt.self, from: data)

        XCTAssertEqual(receipt.uploadID, "u1")
        XCTAssertEqual(receipt.relativePath, "Docs/note.md")
        XCTAssertEqual(receipt.deviceID, "mac-1")
    }

    func testRunOutcomeDecodesImmediateRunContract() throws {
        let data = Data(
            #"{"run_id":"r1","status":"ok","pages":2,"conflicts":1,"errors":0,"exit_code":0,"git_commit":"abc","already_running":false,"written":3}"#.utf8
        )

        let outcome = try JSONDecoder().decode(RunOutcome.self, from: data)

        XCTAssertEqual(outcome.runID, "r1")
        XCTAssertEqual(outcome.pages, 2)
        XCTAssertEqual(outcome.gitCommit, "abc")
        XCTAssertFalse(outcome.alreadyRunning)
    }

    func testMarkdownSummaryProducesNotificationSizedPlainText() {
        let markdown = """
        # 2026-08-28 브리핑
        ## 오늘의 추천
        - 계약서를 확인한다.[^abcd1234]
        - **백업** 상태를 점검한다.
        """

        let summary = MarkdownSummary.plainText(markdown, limit: 60)

        XCTAssertFalse(summary.contains("#"))
        XCTAssertFalse(summary.contains("[^"))
        XCTAssertFalse(summary.contains("**"))
        XCTAssertLessThanOrEqual(summary.count, 60)
        XCTAssertTrue(summary.contains("계약서"))
    }
}

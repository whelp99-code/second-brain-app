// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SecondBrainMac",
    defaultLocalization: "ko",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .library(name: "SecondBrainCore", targets: ["SecondBrainCore"]),
        .executable(name: "SecondBrainMac", targets: ["SecondBrainMac"])
    ],
    targets: [
        .target(
            name: "SecondBrainCore",
            path: "Sources/SecondBrainCore"
        ),
        .executableTarget(
            name: "SecondBrainMac",
            dependencies: ["SecondBrainCore"],
            path: "Sources/SecondBrainMac"
        ),
        .testTarget(
            name: "SecondBrainCoreTests",
            dependencies: ["SecondBrainCore"],
            path: "Tests/SecondBrainCoreTests"
        ),
        .testTarget(
            name: "SecondBrainMacTests",
            dependencies: ["SecondBrainCore", "SecondBrainMac"],
            path: "Tests/SecondBrainMacTests"
        )
    ]
)

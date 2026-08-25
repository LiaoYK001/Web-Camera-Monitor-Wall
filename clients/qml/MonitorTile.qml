import QtQuick
import QtQuick.Controls
import org.freedesktop.gstreamer.Qt6GLVideoItem 1.0

Item {
    id: root
    property string streamSessionId
    property string streamCameraId
    property string displayTitle: "Camera"
    property var streamMedia
    property string streamTopology
    property string streamArchiveTopology
    property string streamFallbackReason
    property int streamReconnectCount: 0
    property bool focused: false
    property alias videoItem: video

    Component.onCompleted: clientController.attachStream(focused, streamSessionId, video)

    Rectangle {
        anchors.fill: parent
        anchors.margins: 2
        color: "#05070a"
        border.color: root.focused ? "#46a6ff" : "#273244"
        border.width: root.focused ? 2 : 1
        GstGLVideoItem { id: video; anchors.fill: parent }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: Math.max(38, detailText.implicitHeight + 12)
            color: "#c010141c"
            Column {
                id: detailText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 8
                Text { color: "white"; text: root.displayTitle; font.bold: true; elide: Text.ElideRight; width: parent.width }
                Text {
                    color: root.streamMedia && root.streamMedia.hardwareDecode ? "#55d88a" : "#ffbf69"
                    width: parent.width
                    elide: Text.ElideRight
                    text: root.streamTopology + " · " +
                          (root.streamMedia ? root.streamMedia.decoder : "waiting") +
                          (root.streamMedia ? " · " + root.streamMedia.currentFps.toFixed(1) + " fps" : "") +
                          (root.streamMedia && root.streamMedia.videoWidth > 0 ?
                               " · " + root.streamMedia.videoWidth + "×" + root.streamMedia.videoHeight : "") +
                          (root.streamMedia && root.streamMedia.framesDropped > 0 ?
                              " · dropped " + root.streamMedia.framesDropped : "") +
                          (root.streamReconnectCount > 0 ? " · reconnect " + root.streamReconnectCount : "")
                }
                Text {
                    visible: root.streamFallbackReason.length > 0
                    color: "#ff8f8f"
                    width: parent.width
                    elide: Text.ElideRight
                    text: root.streamFallbackReason
                }
            }
        }

        TapHandler {
            acceptedButtons: Qt.LeftButton
            onDoubleTapped: if (!root.focused) clientController.focusCamera(root.streamCameraId)
        }
        Button {
            visible: root.focused
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.margins: 10
            text: "Close focus"
            onClicked: clientController.closeFocus()
        }
        Row {
            visible: root.focused
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.margins: 10
            spacing: 6
            Button {
                text: root.streamMedia && !root.streamMedia.muted ? "Mute" : "Listen"
                onClicked: clientController.setListening(
                    root.focused, root.streamSessionId, root.streamMedia && root.streamMedia.muted)
            }
            Button {
                visible: clientController.cameraHasPermission(root.streamCameraId, "talk")
                text: clientController.talkActive ? "Release Talk" : "Hold Talk"
                onPressed: if (!clientController.talkActive) clientController.startTalk(root.streamCameraId)
                onReleased: if (clientController.talkActive) clientController.finishTalk()
            }
            Button {
                visible: clientController.cameraHasPermission(root.streamCameraId, "snapshot")
                text: "Camera snapshot"
                onClicked: clientController.saveSnapshot(
                    root.streamCameraId, clientController.suggestedCapturePath("jpg"))
            }
            Button {
                visible: clientController.cameraHasPermission(root.streamCameraId, "snapshot")
                text: "Local screenshot"
                onClicked: clientController.saveLocalScreenshot(
                    root.streamCameraId, video, clientController.suggestedCapturePath("png"))
            }
            Button {
                visible: clientController.cameraHasPermission(root.streamCameraId, "record-local")
                text: root.streamMedia && root.streamMedia.recording ? "Stop MKV" : "Record MKV"
                onClicked: {
                    if (root.streamMedia && root.streamMedia.recording)
                        clientController.stopManualRecording(root.focused, root.streamSessionId)
                    else
                        clientController.startManualRecording(root.focused, root.streamSessionId,
                            clientController.suggestedCapturePath("mkv"))
                }
            }
        }
        Grid {
            visible: root.focused && clientController.cameraHasPermission(root.streamCameraId, "ptz")
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.rightMargin: 12
            columns: 3
            spacing: 4
            Item { width: 44; height: 36 }
            Button {
                width: 44; height: 36; text: "▲"
                onPressed: clientController.movePtz(root.streamCameraId, 0, 0.5, 0)
                onReleased: clientController.stopPtz(root.streamCameraId)
            }
            Item { width: 44; height: 36 }
            Button {
                width: 44; height: 36; text: "◀"
                onPressed: clientController.movePtz(root.streamCameraId, -0.5, 0, 0)
                onReleased: clientController.stopPtz(root.streamCameraId)
            }
            Button {
                width: 44; height: 36; text: "■"
                onClicked: clientController.stopPtz(root.streamCameraId)
            }
            Button {
                width: 44; height: 36; text: "▶"
                onPressed: clientController.movePtz(root.streamCameraId, 0.5, 0, 0)
                onReleased: clientController.stopPtz(root.streamCameraId)
            }
            Button {
                width: 44; height: 36; text: "−"
                onPressed: clientController.movePtz(root.streamCameraId, 0, 0, -0.5)
                onReleased: clientController.stopPtz(root.streamCameraId)
            }
            Button {
                width: 44; height: 36; text: "▼"
                onPressed: clientController.movePtz(root.streamCameraId, 0, -0.5, 0)
                onReleased: clientController.stopPtz(root.streamCameraId)
            }
            Button {
                width: 44; height: 36; text: "+"
                onPressed: clientController.movePtz(root.streamCameraId, 0, 0, 0.5)
                onReleased: clientController.stopPtz(root.streamCameraId)
            }
        }
    }
}

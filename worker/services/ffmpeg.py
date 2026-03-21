import subprocess
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class FFMPEG:
    def __init__(self):
        self.ffmpeg_path = "ffmpeg" # Assuming it's in PATH as per spec

    def stitch_audio(self, input_paths, output_path):
        """
        Stitch multiple audio files into one.
        Using a concat filter or a simple concat command.
        """
        if not input_paths:
            logger.error("No input paths provided for stitching")
            return None
        
        # Create a temporary file list for ffmpeg concat
        temp_list_path = Path(output_path).parent / "concat_list.txt"
        with open(temp_list_path, "w", encoding='utf-8') as f:
            for path in input_paths:
                # ffmpeg requires paths to be escaped or in a specific format for concat
                abs_path = Path(path).resolve()
                f.write(f"file '{abs_path}'\n")
        
        try:
            cmd = [
                self.ffmpeg_path,
                "-y", # Overwrite output
                "-f", "concat",
                "-safe", "0",
                "-i", str(temp_list_path),
                "-c:a", "libmp3lame", # Ensure we encode as MP3 correctly
                "-q:a", "2", # High quality (Matches app requirements)
                str(output_path)
            ]
            
            logger.info(f"Running ffmpeg: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info("FFMPEG completed successfully")
            
            # Remove temp list
            if os.path.exists(temp_list_path):
                os.remove(temp_list_path)
                
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"FFMPEG error: {e.stderr}")
            if os.path.exists(temp_list_path):
                os.remove(temp_list_path)
            raise

    def get_duration(self, file_path):
        """
        Get duration of an audio/video file in seconds using ffprobe.
        """
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"FFPROBE error: {str(e)}")
            return 0.0

    def add_background_music(self, speech_path, music_path, output_path, music_volume=0.15):
        """
        Overlay background music onto speech audio.
        """
        try:
            # -filter_complex for mixing
            # [0:a] is speech, [1:a] is music
            # music is looped and volume is adjusted
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-i", str(speech_path),
                "-stream_loop", "-1", # Loop music infinitely
                "-i", str(music_path),
                "-filter_complex", f"[1:a]volume={music_volume}[music];[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[out]",
                "-map", "[out]",
                "-c:a", "libmp3lame",
                "-q:a", "2", # High quality
                str(output_path)
            ]
            
            logger.info(f"Adding background music: {' '.join(cmd)}")
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"FFMPEG mix error: {e.stderr}")
            raise

    def convert_to_mp3(self, input_path, output_path):
        """
        Convert any audio file to high-quality MP3.
        """
        try:
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-i", str(input_path),
                "-c:a", "libmp3lame",
                "-q:a", "2", # High quality
                str(output_path)
            ]
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"FFMPEG conversion error: {e.stderr}")
            raise

    def create_slideshow_video(self, image_durations, audio_path, output_path, width=1920, height=1080):
        """
        Create an MP4 slideshow from a list of (image_path, duration_ms) and an audio file.
        image_durations: List of (Path, duration_ms)
        """
        # Create temporary file list for concat demuxer
        temp_list_path = Path(output_path).parent / "video_concat.txt"
        with open(temp_list_path, "w", encoding='utf-8') as f:
            for img_path, duration_ms in image_durations:
                # Convert duration to seconds
                dur_s = duration_ms / 1000.0
                abs_path = Path(img_path).resolve()
                f.write(f"file '{abs_path}'\n")
                f.write(f"duration {dur_s}\n")
            
            # The last image needs to be repeated once without duration for some ffmpeg versions
            if image_durations:
                f.write(f"file '{Path(image_durations[-1][0]).resolve()}'\n")

        try:
            # -pix_fmt yuv420p is required for most players (QuickTime, YouTube)
            # scale and crop to the target width/height
            # "force_original_aspect_ratio=increase" ensures it fills the frame
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(temp_list_path),
                "-i", str(audio_path),
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},format=yuv420p",
                "-c:v", "libx264",
                "-profile:v", "main",
                "-level:v", "4.0",
                "-preset", "medium",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest", # End video when audio ends
                str(output_path)
            ]
            
            logger.info(f"Generating Slideshow MP4: {' '.join(cmd)}")
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            if os.path.exists(temp_list_path):
                os.remove(temp_list_path)
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"FFMPEG video error: {e.stderr}")
            if os.path.exists(temp_list_path):
                os.remove(temp_list_path)
            raise

ffmpeg = FFMPEG()
